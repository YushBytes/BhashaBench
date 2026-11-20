"""Connected bots ("bring your own bot").

Thin routes over `app.services.integration_service`, which checks access:
reading needs `view` in the project, saving, changing and checking need
`edit`, deleting needs `delete`. A foreign integration is a 404.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Response, status

from app.api.deps import CurrentPrincipal, DbSession, SettingsDep
from app.auth.permissions import Permission
from app.models.bot_integration import BotIntegration, IntegrationProtocol
from app.pipeline.bots.http_text import CAPABILITIES as HTTP_CAPABILITIES
from app.pipeline.bots.ws_voice import CAPABILITIES as WS_CAPABILITIES
from app.schemas.common import ErrorResponse
from app.schemas.integration import (
    CapabilityRead,
    IntegrationCheckRequest,
    IntegrationCheckResponse,
    IntegrationCreate,
    IntegrationRead,
    IntegrationUpdate,
    LastCheckRead,
)
from app.services import integration_service

router = APIRouter(tags=["bot-integrations"])

_ERRORS: dict[int | str, dict[str, object]] = {
    status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse},
    status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
    status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    status.HTTP_409_CONFLICT: {"model": ErrorResponse},
    status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorResponse},
}

_DECLARED = {
    IntegrationProtocol.HTTP: (HTTP_CAPABILITIES, "text_bot_test"),
    IntegrationProtocol.WS_VOICE: (WS_CAPABILITIES, "external_bot_test"),
}


def _read(integration: BotIntegration) -> IntegrationRead:
    caps, mode = _DECLARED[integration.protocol]
    return IntegrationRead(
        id=integration.id,
        project_id=integration.project_id,
        name=integration.name,
        protocol=integration.protocol,
        url=integration.url,
        credential_hint=integration.credential_hint,
        default_language=integration.default_language,
        check_status=integration.check_status,
        last_checked_at=integration.last_checked_at,
        last_check=LastCheckRead(**integration.last_check) if integration.last_check else None,
        declared=CapabilityRead(
            contacts_external_system=caps.contacts_external_system,
            supports_sessions=caps.supports_sessions,
            requires_credentials=caps.requires_credentials,
            accepts_containers=sorted(caps.accepts_containers),
            supports_caller_barge_in=caps.supports_caller_barge_in,
            execution_mode=mode,
            notes=list(caps.notes),
        ),
        created_at=integration.created_at,
        updated_at=integration.updated_at,
    )


@router.get(
    "/projects/{project_id}/bot-integrations",
    summary="List the project's connected bots",
    responses=_ERRORS,
)
def list_integrations(
    project_id: uuid.UUID, principal: CurrentPrincipal, session: DbSession
) -> list[IntegrationRead]:
    return [_read(i) for i in integration_service.list_for_project(session, principal, project_id)]


@router.post(
    "/projects/{project_id}/bot-integrations",
    status_code=status.HTTP_201_CREATED,
    summary="Connect a bot",
    description=(
        "Saves the bot's protocol, URL and token (encrypted). Saving contacts "
        "nothing, so the integration is `unverified` until `POST .../check` succeeds."
    ),
    responses=_ERRORS,
)
def create_integration(
    project_id: uuid.UUID,
    payload: IntegrationCreate,
    principal: CurrentPrincipal,
    session: DbSession,
    settings: SettingsDep,
) -> IntegrationRead:
    integration = integration_service.create(
        session,
        principal,
        settings,
        project_id=project_id,
        name=payload.name,
        protocol=payload.protocol,
        url=payload.url,
        token=payload.token,
        default_language=payload.default_language,
    )
    session.commit()
    return _read(integration)


@router.get("/bot-integrations/{integration_id}", summary="One connected bot", responses=_ERRORS)
def get_integration(
    integration_id: uuid.UUID, principal: CurrentPrincipal, session: DbSession
) -> IntegrationRead:
    return _read(integration_service.require(session, principal, integration_id, Permission.VIEW))


@router.patch(
    "/bot-integrations/{integration_id}",
    summary="Change a connected bot",
    description="Changing the URL or the token resets `check_status` to `unverified`.",
    responses=_ERRORS,
)
def update_integration(
    integration_id: uuid.UUID,
    payload: IntegrationUpdate,
    principal: CurrentPrincipal,
    session: DbSession,
    settings: SettingsDep,
) -> IntegrationRead:
    integration = integration_service.update(
        session,
        principal,
        settings,
        integration_id,
        name=payload.name,
        url=payload.url,
        token=payload.token,
        default_language=payload.default_language,
    )
    session.commit()
    return _read(integration)


@router.delete(
    "/bot-integrations/{integration_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a connected bot",
    description="Runs that used it keep its id and name in their own evidence.",
    responses=_ERRORS,
)
def delete_integration(
    integration_id: uuid.UUID, principal: CurrentPrincipal, session: DbSession
) -> Response:
    integration_service.delete(session, principal, integration_id)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/bot-integrations/{integration_id}/check",
    summary="Check the connection",
    description=(
        "Contacts the bot through the same adapter a run uses, with the same "
        "outbound rules and address pinning. `http`: opens a session, sends one "
        "short text turn, closes it. `ws_voice`: opens the WebSocket and asks for "
        "a session in the exact audio format a run streams. The outcome is "
        "recorded either way; only success makes the integration `connected`."
    ),
    responses=_ERRORS,
)
def check_integration(
    integration_id: uuid.UUID,
    principal: CurrentPrincipal,
    session: DbSession,
    settings: SettingsDep,
    payload: IntegrationCheckRequest | None = None,
) -> IntegrationCheckResponse:
    integration, result = integration_service.check(
        session,
        principal,
        settings,
        integration_id,
        language=payload.language if payload else None,
    )
    session.commit()
    return IntegrationCheckResponse(integration=_read(integration), ok=result.ok)


__all__ = ["router"]
