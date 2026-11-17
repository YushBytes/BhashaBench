"""Authentication endpoints: sign-up, login, logout, the current user, password.

Cookie attributes are chosen here, once: `HttpOnly` (page script cannot read
the token), `SameSite=Strict` (a cross-site request does not carry it),
`Secure` outside local development, `Path=/`, and a `Max-Age` equal to the
session's absolute lifetime. See docs/AUTH.md.
"""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from app.api.deps import SESSION_COOKIE, CurrentPrincipal, DbSession, SettingsDep
from app.core.config import Settings
from app.models.identity import AuthSession
from app.repositories import identity as repo
from app.schemas.auth import (
    LoginRequest,
    LoginResponse,
    MembershipRead,
    MeResponse,
    PasswordChangeRequest,
    PasswordChangeResponse,
    SignupRequest,
    UserRead,
)
from app.schemas.common import ErrorResponse
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])

_401 = {status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse}}


def _set_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=int(settings.auth_session_ttl_hours * 3600),
        path="/",
        secure=settings.auth_cookie_secure,
        httponly=True,
        samesite="strict",
    )


def _clear_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        SESSION_COOKIE,
        path="/",
        secure=settings.auth_cookie_secure,
        httponly=True,
        samesite="strict",
    )


@router.post(
    "/signup",
    status_code=status.HTTP_201_CREATED,
    summary="Create an account and its own workspace",
    description=(
        "Disabled unless `AUTH_ALLOW_SIGNUP=true` (403 otherwise). The new user owns a new "
        "workspace with a `Default` project. Does not sign in; call /auth/login next."
    ),
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
        status.HTTP_409_CONFLICT: {"model": ErrorResponse},
    },
)
def signup(body: SignupRequest, session: DbSession, settings: SettingsDep) -> UserRead:
    user, _ = auth_service.signup(
        session,
        settings,
        email=body.email,
        display_name=body.display_name,
        password=body.password.get_secret_value(),
        workspace_name=body.workspace_name,
    )
    return UserRead(id=user.id, email=user.email, display_name=user.display_name)


@router.post(
    "/login",
    summary="Sign in",
    description=(
        "Every failure is the same 401 with the same message - unknown email, wrong "
        "password, deactivated or locked account - so the endpoint cannot be used to "
        "learn which accounts exist. Repeated failures lock the account temporarily."
    ),
    responses=_401,
)
def login(
    body: LoginRequest, response: Response, session: DbSession, settings: SettingsDep
) -> LoginResponse:
    issued = auth_service.login(
        session, settings, email=body.email, password=body.password.get_secret_value()
    )
    user = UserRead(
        id=issued.user.id, email=issued.user.email, display_name=issued.user.display_name
    )
    if body.session_type == "cookie":
        _set_cookie(response, issued.token, settings)
        return LoginResponse(user=user, expires_at=issued.record.expires_at, session_type="cookie")
    return LoginResponse(
        user=user, expires_at=issued.record.expires_at, session_type="bearer", token=issued.token
    )


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Sign out: revoke this session and clear the cookie",
    responses=_401,
)
def logout(principal: CurrentPrincipal, session: DbSession, settings: SettingsDep) -> Response:
    auth_service.logout(session, principal)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    _clear_cookie(response, settings)
    return response


@router.get("/me", summary="The signed-in user and their workspaces", responses=_401)
def me(principal: CurrentPrincipal, session: DbSession) -> MeResponse:
    record = session.get(AuthSession, principal.session_id) if principal.session_id else None
    return MeResponse(
        user=UserRead(
            id=principal.user_id, email=principal.email, display_name=principal.display_name
        ),
        workspaces=[
            MembershipRead(
                workspace_id=w.id, workspace_name=w.name, workspace_slug=w.slug, role=m.role
            )
            for m, w in repo.memberships_of_user(session, principal.user_id)
        ],
        session_expires_at=None if record is None else record.expires_at,
    )


@router.post(
    "/password",
    summary="Change the password and sign out every other session",
    responses={**_401, status.HTTP_409_CONFLICT: {"model": ErrorResponse}},
)
def change_password(
    body: PasswordChangeRequest,
    principal: CurrentPrincipal,
    session: DbSession,
    settings: SettingsDep,
) -> PasswordChangeResponse:
    revoked = auth_service.change_password(
        session,
        settings,
        principal,
        current_password=body.current_password.get_secret_value(),
        new_password=body.new_password.get_secret_value(),
    )
    return PasswordChangeResponse(other_sessions_revoked=revoked)


__all__ = ["router"]
