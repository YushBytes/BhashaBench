"""Shared FastAPI dependencies."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Query, Request, WebSocket, WebSocketException
from sqlalchemy.orm import Session
from starlette.requests import HTTPConnection

from app.core.config import Settings, get_settings
from app.db.session import check_database_connection, get_db
from app.services import auth_service
from app.services.auth_service import Principal
from app.services.errors import PermissionDeniedError, UnauthenticatedError

SettingsDep = Annotated[Settings, Depends(get_settings)]
"""Injected application settings.

Declared as a dependency rather than imported directly in handlers so that
tests can override it with `app.dependency_overrides`.
"""

DbSession = Annotated[Session, Depends(get_db)]
"""Injected request-scoped database session.

The underlying dependency rolls back and closes in a `finally`, so a handler
that raises cannot leak a connection or leave a transaction open. Tests
override `get_db` to bind a session to their own transaction.
"""


@dataclass(frozen=True, slots=True)
class Pagination:
    """Validated page window."""

    limit: int
    offset: int


def pagination_params(
    limit: Annotated[
        int,
        Query(
            ge=1,
            # Capped so a client cannot ask for the whole table in one request
            # and turn a list endpoint into an accidental denial of service.
            le=100,
            description="Maximum items to return.",
        ),
    ] = 20,
    offset: Annotated[int, Query(ge=0, description="Items to skip.")] = 0,
) -> Pagination:
    """Parse and validate `limit`/`offset` query parameters."""
    return Pagination(limit=limit, offset=offset)


PaginationParams = Annotated[Pagination, Depends(pagination_params)]
"""Injected pagination window, shared by every list endpoint."""


def get_database_probe() -> Callable[[], tuple[bool, str]]:
    """Return the callable the health endpoint uses to probe the database.

    Injected rather than imported so a test can supply a stub. Without this
    seam the probe would always use the process-wide engine built from global
    settings, which means a test that overrides `Settings` would still report
    on whatever database the developer's `.env` happens to point at - the
    endpoint would look healthy for the wrong reason.
    """
    return check_database_connection


DatabaseProbe = Annotated[Callable[[], tuple[bool, str]], Depends(get_database_probe)]
"""Injected database health probe, returning `(reachable, detail)`."""


# ---------------------------------------------------------------------------
# Authentication (Phase 14)
# ---------------------------------------------------------------------------

SESSION_COOKIE = "bb_session"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _same_origin(request: HTTPConnection, origin: str) -> bool:
    return origin.rstrip("/") == str(request.base_url).rstrip("/")


def _check_cookie_origin(request: HTTPConnection, settings: Settings) -> None:
    """Refuse a cookie-authenticated write from a foreign origin.

    The cookie is `SameSite=Strict`, so a modern browser does not send it on
    a cross-site request at all; this is the second layer for browsers that
    do, and for same-site-but-cross-origin pages. A bearer token needs no such
    check: a browser never attaches one by itself.
    """
    origin = request.headers.get("origin")
    if origin is None:
        return  # not a browser cross-origin request; SameSite already applies
    allowed = {o.rstrip("/") for o in settings.cors_origins}
    if origin != "null" and (origin.rstrip("/") in allowed or _same_origin(request, origin)):
        return
    raise PermissionDeniedError(f"cross-origin request from {origin!r} refused")


def credential_of(request: HTTPConnection) -> tuple[str, str] | None:
    """`(token, source)` from the Authorization header or the cookie."""
    header = request.headers.get("authorization")
    if header is not None:
        scheme, _, value = header.partition(" ")
        if scheme.lower() != "bearer" or not value.strip():
            raise UnauthenticatedError("Authorization must be 'Bearer <token>'")
        return value.strip(), "bearer"
    cookie = request.cookies.get(SESSION_COOKIE)
    if cookie:
        return cookie, "cookie"
    return None


def get_principal(request: Request, session: DbSession, settings: SettingsDep) -> Principal:
    """The authenticated caller, or 401. Tests may override this dependency."""
    credential = credential_of(request)
    if credential is None:
        raise UnauthenticatedError(auth_service.SESSION_INVALID)
    token, source = credential
    if source == "cookie" and request.method not in SAFE_METHODS:
        _check_cookie_origin(request, settings)
    return auth_service.resolve(session, settings, token)


CurrentPrincipal = Annotated[Principal, Depends(get_principal)]
"""The authenticated caller. Declaring it on a route is what makes it private."""


WS_POLICY_VIOLATION = 1008


def get_websocket_principal(
    websocket: WebSocket, session: DbSession, settings: SettingsDep
) -> Principal:
    """Authenticate a WebSocket handshake, or close it with 1008.

    Browsers send cookies on the handshake and cannot set headers, so the
    cookie is the browser path and `Authorization: Bearer` the scripted one.
    The Origin check applies to every cookie handshake, not only to "unsafe"
    methods: a cross-site page opening a socket with the victim's cookie is
    the WebSocket form of CSRF.
    """
    try:
        credential = credential_of(websocket)
        if credential is None:
            raise UnauthenticatedError(auth_service.SESSION_INVALID)
        token, source = credential
        if source == "cookie":
            _check_cookie_origin(websocket, settings)
        return auth_service.resolve(session, settings, token)
    except (UnauthenticatedError, PermissionDeniedError) as exc:
        raise WebSocketException(code=WS_POLICY_VIOLATION, reason=str(exc)[:120]) from exc


WebSocketPrincipal = Annotated[Principal, Depends(get_websocket_principal)]
