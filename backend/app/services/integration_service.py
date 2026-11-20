"""Bring your own bot: store, check and use a workspace's connected chatbot.

The rules this service holds, so neither the API nor a future CLI can skip
them:

- **Access is the project's.** Reading needs `view` in the project, saving,
  changing and checking need `edit`, deleting needs `delete`. An integration
  in a workspace the caller is not in is a 404, the same as one that does not
  exist.
- **The token is sealed on the way in and opened only to build an adapter.**
  No function here returns it; the API sees `credential_hint` only.
- **Saving is not connecting.** A saved integration is `unverified`. Only a
  successful `check` through the real adapter makes it `connected`, and any
  change to the URL or the token puts it back to `unverified`.
- **Runs use connected integrations only**, from the run's own project, and
  the run records which integration (id, name, protocol, URL host) it used.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from pydantic import SecretStr
from sqlalchemy.orm import Session

from app.auth.permissions import Permission
from app.core import languages
from app.core.config import Settings
from app.core.secretbox import CredentialUnreadableError, hint, open_sealed, seal
from app.models.bot_integration import BotIntegration, CheckStatus, IntegrationProtocol
from app.models.suite import TestSuite
from app.pipeline.bots.probe import ProbeResult, probe
from app.pipeline.bots.protocol import BotAdapter
from app.pipeline.bots.registry import build_integration_adapter, integration_policy
from app.repositories import bot_integrations as repo
from app.services import access_service
from app.services.auth_service import Principal
from app.services.errors import ConflictError, InvalidRequestError, NotFoundError
from app.utils.timing import utc_now

RESOURCE = "BotIntegration"
MIN_TOKEN_CHARS = 16
MAX_TOKEN_CHARS = 4096
MAX_URL_CHARS = 2048

SCHEMES: dict[IntegrationProtocol, frozenset[str]] = {
    IntegrationProtocol.HTTP: frozenset({"https", "http"}),
    IntegrationProtocol.WS_VOICE: frozenset({"wss", "ws"}),
}
"""Plain `http`/`ws` pass this shape check and are then refused by the
outbound guard unless the target is loopback (development) - the guard, not
this table, is the security control."""


def _disabled_error() -> ConflictError:
    return ConflictError(
        "connecting your own bot is disabled on this deployment (BOT_INTEGRATIONS_ENABLED is false)"
    )


def _require_enabled(settings: Settings) -> None:
    if not settings.bot_integrations_enabled:
        raise _disabled_error()


def validate_url(protocol: IntegrationProtocol, url: str) -> str:
    """Shape only: scheme for the protocol, a host, no credential, no fragment.

    Whether the host may be contacted is decided when it is checked, by the
    outbound guard - saving never touches the network.

    Raises:
        InvalidRequestError: the URL cannot be used with this protocol.
    """
    url = url.strip()
    if not url:
        raise InvalidRequestError("the bot URL is empty")
    if len(url) > MAX_URL_CHARS:
        raise InvalidRequestError(f"the bot URL is longer than {MAX_URL_CHARS} characters")
    try:
        parts = urlsplit(url)
        parts.port  # noqa: B018 - raises on a malformed port
    except ValueError as exc:
        raise InvalidRequestError(f"the bot URL is malformed: {exc}") from exc
    allowed = SCHEMES[protocol]
    if parts.scheme.lower() not in allowed:
        expected = " or ".join(f"{s}://" for s in sorted(allowed, reverse=True))
        raise InvalidRequestError(
            f"a {protocol.value} bot URL must start with {expected}; "
            f"got '{parts.scheme or '(no scheme)'}'"
        )
    if parts.username is not None or parts.password is not None:
        raise InvalidRequestError(
            "the bot URL carries a username or password; put the credential in the "
            "token field, where it is encrypted, not in the URL"
        )
    if parts.fragment:
        raise InvalidRequestError("the bot URL has a #fragment, which no request can send")
    if not parts.hostname:
        raise InvalidRequestError("the bot URL has no host")
    return url


def _validate_token(token: str) -> str:
    if not MIN_TOKEN_CHARS <= len(token) <= MAX_TOKEN_CHARS:
        raise InvalidRequestError(
            f"the bot's token must be {MIN_TOKEN_CHARS} to {MAX_TOKEN_CHARS} characters; "
            "both protocols send it as `Authorization: Bearer <token>`"
        )
    if any(c.isspace() for c in token):
        raise InvalidRequestError("the bot's token contains whitespace")
    return token


def _validate_name(name: str) -> str:
    name = name.strip()
    if not 1 <= len(name) <= 120:
        raise InvalidRequestError("the integration name must be 1 to 120 characters")
    return name


def _language(code: str) -> str:
    try:
        return languages.validate_tag(code)
    except languages.UnsupportedLanguageError as exc:
        raise InvalidRequestError(str(exc)) from exc


def _get_for(
    session: Session, principal: Principal, integration_id: uuid.UUID, permission: Permission
) -> BotIntegration:
    integration = repo.get(session, integration_id)
    if integration is None:
        raise NotFoundError(RESOURCE, integration_id)
    try:
        access_service.require_project(session, principal, integration.project_id, permission)
    except NotFoundError as exc:
        raise NotFoundError(RESOURCE, integration_id) from exc
    return integration


def require(
    session: Session, principal: Principal, integration_id: uuid.UUID, permission: Permission
) -> BotIntegration:
    """The integration, if the caller holds `permission` in its project."""
    return _get_for(session, principal, integration_id, permission)


def list_for_project(
    session: Session, principal: Principal, project_id: uuid.UUID
) -> list[BotIntegration]:
    access_service.require_project(session, principal, project_id, Permission.VIEW)
    return repo.list_for_projects(session, [project_id])


def create(
    session: Session,
    principal: Principal,
    settings: Settings,
    *,
    project_id: uuid.UUID,
    name: str,
    protocol: IntegrationProtocol,
    url: str,
    token: SecretStr,
    default_language: str,
) -> BotIntegration:
    access_service.require_project(session, principal, project_id, Permission.EDIT)
    _require_enabled(settings)
    name = _validate_name(name)
    if repo.get_by_name(session, project_id, name) is not None:
        raise ConflictError(f"an integration named '{name}' already exists in this project")
    plain = _validate_token(token.get_secret_value())
    integration_id = uuid.uuid4()
    integration = BotIntegration(
        id=integration_id,
        project_id=project_id,
        name=name,
        protocol=protocol,
        url=validate_url(protocol, url),
        credential_sealed=seal(
            plain, secret_key=settings.secret_key, bound_to=integration_id.bytes
        ),
        credential_hint=hint(plain),
        default_language=_language(default_language),
        created_by=principal.user_id,
        check_status=CheckStatus.UNVERIFIED,
    )
    return repo.add(session, integration)


def update(
    session: Session,
    principal: Principal,
    settings: Settings,
    integration_id: uuid.UUID,
    *,
    name: str | None = None,
    url: str | None = None,
    token: SecretStr | None = None,
    default_language: str | None = None,
) -> BotIntegration:
    integration = _get_for(session, principal, integration_id, Permission.EDIT)
    changed_target = False
    if name is not None:
        name = _validate_name(name)
        clash = repo.get_by_name(session, integration.project_id, name)
        if clash is not None and clash.id != integration.id:
            raise ConflictError(f"an integration named '{name}' already exists in this project")
        integration.name = name
    if url is not None:
        url = validate_url(integration.protocol, url)
        changed_target = changed_target or url != integration.url
        integration.url = url
    if token is not None:
        _require_enabled(settings)
        plain = _validate_token(token.get_secret_value())
        integration.credential_sealed = seal(
            plain, secret_key=settings.secret_key, bound_to=integration.id.bytes
        )
        integration.credential_hint = hint(plain)
        changed_target = True
    if default_language is not None:
        integration.default_language = _language(default_language)
    if changed_target:
        # A check proved the *old* URL and token. It proves nothing about these.
        integration.check_status = CheckStatus.UNVERIFIED
        integration.last_check = None
        integration.last_checked_at = None
    session.add(integration)
    session.flush()
    return integration


def delete(session: Session, principal: Principal, integration_id: uuid.UUID) -> None:
    integration = _get_for(session, principal, integration_id, Permission.DELETE)
    repo.delete(session, integration)


def _token(integration: BotIntegration, settings: Settings) -> SecretStr:
    try:
        return SecretStr(
            open_sealed(
                integration.credential_sealed,
                secret_key=settings.secret_key,
                bound_to=integration.id.bytes,
            )
        )
    except CredentialUnreadableError as exc:
        raise ConflictError(
            f"the stored token for integration '{integration.name}' cannot be read: {exc}"
        ) from exc


def check(
    session: Session,
    principal: Principal,
    settings: Settings,
    integration_id: uuid.UUID,
    *,
    language: str | None = None,
    resolver: Any = None,
) -> tuple[BotIntegration, ProbeResult]:
    """Run a connection check through the real adapter and record the outcome.

    The outcome is recorded whether it succeeded or failed: a failed check is
    evidence too, and it demotes a previously connected integration.
    """
    integration = _get_for(session, principal, integration_id, Permission.EDIT)
    _require_enabled(settings)
    token = _token(integration, settings)
    result = asyncio.run(
        probe(
            integration.protocol.value,
            url=integration.url,
            token=token,
            policy=integration_policy(integration.url, settings),
            language=_language(language) if language else integration.default_language,
            timeout_seconds=settings.bot_http_timeout_seconds,
            resolver=resolver,
        )
    )
    integration.check_status = CheckStatus.CONNECTED if result.ok else CheckStatus.FAILED
    integration.last_checked_at = utc_now()
    integration.last_check = result.as_record()
    session.add(integration)
    session.flush()
    return integration, result


@dataclass(frozen=True, slots=True)
class RunIntegration:
    """What a run records about the integration it used."""

    integration_id: uuid.UUID
    name: str
    protocol: str
    host: str
    checked_at: str | None

    def as_metadata(self) -> dict[str, Any]:
        return {
            "id": str(self.integration_id),
            "name": self.name,
            "protocol": self.protocol,
            "host": self.host,
            "connection_checked_at": self.checked_at,
        }


def for_new_run(
    session: Session,
    principal: Principal,
    settings: Settings,
    integration_id: uuid.UUID,
    suite_id: uuid.UUID,
    requested_adapter: str | None,
) -> RunIntegration:
    """Validate that a new run in `suite_id` may use this integration.

    Raises:
        NotFoundError: no such integration, or one the caller cannot see.
        InvalidRequestError: another project's integration, or a conflicting
            `bot_adapter`.
        ConflictError: not connected, or integrations are disabled.
    """
    integration = _get_for(session, principal, integration_id, Permission.EDIT)
    _require_enabled(settings)
    suite = session.get(TestSuite, suite_id)
    if suite is None or suite.project_id != integration.project_id:
        raise InvalidRequestError(
            f"integration '{integration.name}' belongs to another project; a run uses "
            "an integration from its own suite's project"
        )
    if requested_adapter and requested_adapter.strip().casefold() != integration.protocol.value:
        raise InvalidRequestError(
            f"bot_adapter '{requested_adapter}' contradicts integration '{integration.name}', "
            f"which speaks '{integration.protocol.value}'; omit bot_adapter"
        )
    if integration.check_status is not CheckStatus.CONNECTED:
        raise ConflictError(
            f"integration '{integration.name}' is {integration.check_status.value}; run a "
            "connection check that succeeds before testing it"
        )
    return RunIntegration(
        integration.id,
        integration.name,
        integration.protocol.value,
        (urlsplit(integration.url).hostname or ""),
        integration.last_checked_at.isoformat() if integration.last_checked_at else None,
    )


def adapter_for(session: Session, settings: Settings, integration_id: uuid.UUID) -> BotAdapter:
    """Build the adapter for a run that recorded this integration.

    Called by the engine factory only, after the route has checked access to
    the *run*. Raises `ConflictError` if the integration was deleted, is no
    longer connected, or its token cannot be read.
    """
    integration = repo.get(session, integration_id)
    if integration is None:
        raise ConflictError(
            f"the bot integration {integration_id} this run was created with has been deleted"
        )
    if not settings.bot_integrations_enabled:
        raise _disabled_error()
    if integration.check_status is not CheckStatus.CONNECTED:
        raise ConflictError(
            f"integration '{integration.name}' is {integration.check_status.value} "
            "since this run was created; check its connection again"
        )
    return build_integration_adapter(
        integration.protocol.value,
        url=integration.url,
        token=_token(integration, settings),
        settings=settings,
    )


__all__ = [
    "RunIntegration",
    "adapter_for",
    "check",
    "create",
    "delete",
    "for_new_run",
    "list_for_project",
    "require",
    "update",
    "validate_url",
]
