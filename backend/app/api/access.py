"""Route dependencies that enforce access from a path parameter.

A route declares, for example, `dependencies=[RunAccess.EDIT]` and FastAPI
reads `run_id` from the path, authenticates the caller and checks their role
before the handler runs. A handler never sees a resource it may not touch,
and the check cannot be forgotten in one branch of the handler body.

Routes whose target comes from the request body (creating a run or a
conversation, copying a scenario into another suite) check that target in
the handler, through `app.services.access_service`.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import Depends, Request

from app.api.deps import CurrentPrincipal, DbSession, SettingsDep, get_principal
from app.auth import signing
from app.auth.permissions import Permission
from app.repositories import identity as identity_repo
from app.services import access_service
from app.services.auth_service import Principal
from app.services.errors import UnauthenticatedError
from app.utils.timing import utc_now


def _suite(permission: Permission) -> Any:
    def check(suite_id: uuid.UUID, principal: CurrentPrincipal, session: DbSession) -> None:
        access_service.require_suite(session, principal, suite_id, permission)

    return Depends(check)


def _scenario(permission: Permission) -> Any:
    def check(scenario_id: uuid.UUID, principal: CurrentPrincipal, session: DbSession) -> None:
        access_service.require_scenario(session, principal, scenario_id, permission)

    return Depends(check)


def _run(permission: Permission) -> Any:
    def check(run_id: uuid.UUID, principal: CurrentPrincipal, session: DbSession) -> None:
        access_service.require_run(session, principal, run_id, permission)

    return Depends(check)


def _conversation(permission: Permission) -> Any:
    def check(conversation_id: uuid.UUID, principal: CurrentPrincipal, session: DbSession) -> None:
        access_service.require_conversation(session, principal, conversation_id, permission)

    return Depends(check)


class _Access:
    def __init__(self, factory: Any) -> None:
        self.VIEW = factory(Permission.VIEW)
        self.EDIT = factory(Permission.EDIT)
        self.DELETE = factory(Permission.DELETE)


SuiteAccess = _Access(_suite)
ScenarioAccess = _Access(_scenario)
RunAccess = _Access(_run)
ConversationAccess = _Access(_conversation)


def _run_audio(
    run_id: uuid.UUID,
    request: Request,
    session: DbSession,
    settings: SettingsDep,
) -> None:
    """A session with `view`, or a valid signed link minted by someone who still has it.

    A link is checked against the exact path it was minted for, its variant
    and its expiry, and then its minter's access is checked again now - so a
    link stops working when its minter is removed from the workspace, is
    deactivated, or `SECRET_KEY` is rotated.
    """
    query = request.query_params
    if "signature" not in query:
        principal = get_principal(request, session, settings)
        access_service.require_run(session, principal, run_id, Permission.VIEW)
        return
    try:
        claims = signing.verify(
            settings.secret_key,
            path=request.url.path,
            variant=query.get("variant"),
            expires=query.get("expires", ""),
            user=query.get("user", ""),
            signature=query.get("signature", ""),
            now=utc_now(),
        )
    except signing.InvalidSignatureError as exc:
        raise UnauthenticatedError(f"the audio link is not valid: {exc}") from exc
    user = identity_repo.get_user(session, claims.user_id)
    if user is None or not user.is_active:
        raise UnauthenticatedError("the audio link is not valid: its owner can no longer sign in")
    minter = Principal(user.id, user.email, user.display_name, session_id=None)
    access_service.require_run(session, minter, run_id, Permission.VIEW)


RunAudioAccess = Depends(_run_audio)
"""For the two audio routes only: a session, or a signed link (`POST .../audio-links`)."""


def _authenticated(principal: CurrentPrincipal) -> None:
    del principal


Authenticated = Depends(_authenticated)
"""For routes that touch no tenant data but must not be anonymous: they spend
provider credit (transcription, speech) or describe server configuration."""

__all__ = [
    "Authenticated",
    "ConversationAccess",
    "RunAccess",
    "RunAudioAccess",
    "ScenarioAccess",
    "SuiteAccess",
]
