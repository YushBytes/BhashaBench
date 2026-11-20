"""Sign-up, login, logout, session resolution and password change.

The service owns the transaction. Two decisions worth knowing before editing:

**Every login failure looks the same.** Unknown email, wrong password,
deactivated account and locked account all raise one `UnauthenticatedError`
with one message, and an unknown email still pays for a full scrypt
verification against a dummy hash, so neither the response nor its timing
says whether an account exists.

**A failed attempt is committed before the refusal is raised.** Otherwise
the request's rollback would undo the counter and the lockout would never
trip.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import lru_cache

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import passwords, tokens
from app.core.config import Settings
from app.models.identity import AuthSession, Role, User, Workspace
from app.repositories import identity as repo
from app.services.errors import (
    ConflictError,
    InvalidRequestError,
    PermissionDeniedError,
    UnauthenticatedError,
)
from app.utils.timing import utc_now

LOGIN_FAILED = "email or password is incorrect, or the account is locked; try again later"
SESSION_INVALID = "authentication required: no valid session"
TOUCH_INTERVAL = timedelta(seconds=60)
DEFAULT_PROJECT_NAME = "Default"
_SLUG_INVALID = re.compile(r"[^a-z0-9-]+")


@dataclass(frozen=True, slots=True)
class Principal:
    """Who is making a request. Carries no role: a role is per workspace."""

    user_id: uuid.UUID
    email: str
    display_name: str
    session_id: uuid.UUID | None
    """`None` only for a principal a test or the CLI constructs directly."""


@dataclass(frozen=True, slots=True)
class IssuedSession:
    token: str
    record: AuthSession
    user: User


@lru_cache(maxsize=4)
def _dummy_hash(log2_n: int) -> str:
    return passwords.hash_password("dummy password for timing equalisation", log2_n=log2_n)


def normalise_email(email: str) -> str:
    return email.strip().lower()


def slugify(name: str) -> str:
    slug = _SLUG_INVALID.sub("-", name.strip().lower()).strip("-")[:63].strip("-")
    return slug or "workspace"


SLUG_ATTEMPTS = 5
"""Fresh suffixes tried before a derived slug is given up on. A collision on
a random 32-bit suffix is already improbable; five makes it negligible."""


def _suffixed(slug: str) -> str:
    return f"{slug[:54]}-{uuid.uuid4().hex[:8]}"


def add_new_workspace(session: Session, *, name: str, slug: str | None = None) -> Workspace:
    """Insert a new workspace and its `Default` project. Never joins one.

    Slugs are global. An explicitly requested `slug` that is taken is a
    `ConflictError`. A slug derived from `name` never is: when another
    workspace holds it, it gets a random suffix, because a refusal would tell
    the caller that some other tenant's workspace of that name exists.

    The unique constraint decides, not a prior lookup: each insert runs in a
    savepoint, so a concurrent request that takes the slug between our check
    and our insert costs a retry with a new suffix rather than a failure.
    Flushes; does not commit.
    """
    name = name.strip()
    explicit = slug is not None
    candidate = slug if slug is not None else slugify(name)
    for _ in range(SLUG_ATTEMPTS):
        if repo.get_workspace_by_slug(session, candidate) is None:
            try:
                with session.begin_nested():
                    workspace = repo.add_workspace(session, name=name or candidate, slug=candidate)
            except IntegrityError:
                pass  # taken concurrently; fall through as if the lookup had seen it
            else:
                repo.add_project(
                    session, workspace_id=workspace.id, name=DEFAULT_PROJECT_NAME, description=None
                )
                return workspace
        if explicit:
            raise ConflictError(f"workspace slug '{candidate}' is taken")
        candidate = _suffixed(slugify(name))
    raise ConflictError("could not allocate a workspace slug; retry")


def _validate_new_password(password: str, email: str) -> None:
    problem = passwords.password_problem(password, email=email)
    if problem is not None:
        raise InvalidRequestError(problem)


def create_user(
    session: Session,
    settings: Settings,
    *,
    email: str,
    display_name: str,
    password: str,
    workspace_name: str | None = None,
    workspace_slug: str | None = None,
    role: Role = Role.OWNER,
    new_workspace: bool = False,
) -> tuple[User, Workspace]:
    """A user and their membership, creating the workspace if it does not exist.

    A new workspace gets a `Default` project, so a fresh account can create a
    suite at once. Joining an existing workspace adds a membership only, and
    only the CLI, which holds database credentials, asks for that. With
    `new_workspace=True` (self-service sign-up) the user always gets a
    workspace of their own: looking a slug up and joining whatever holds it
    would let a concurrent sign-up of the same name make this user an owner
    of a stranger's workspace. Commits.
    """
    email = normalise_email(email)
    if "@" not in email[1:]:
        raise InvalidRequestError("email must contain '@' with something before it")
    _validate_new_password(password, email)
    if repo.get_user_by_email(session, email) is not None:
        raise ConflictError(f"a user with email '{email}' already exists")
    user = repo.add_user(
        session,
        email=email,
        display_name=display_name.strip() or email,
        password_hash=passwords.hash_password(password, log2_n=settings.auth_password_hash_log2_n),
    )
    if new_workspace:
        workspace = add_new_workspace(
            session,
            name=workspace_name or display_name or email.split("@")[0],
            slug=workspace_slug,
        )
    else:
        slug = workspace_slug or slugify(workspace_name or display_name or email.split("@")[0])
        workspace = repo.get_workspace_by_slug(session, slug)
        if workspace is None:
            workspace = add_new_workspace(session, name=workspace_name or slug, slug=slug)
    repo.add_membership(session, workspace_id=workspace.id, user_id=user.id, role=role)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError("the user or workspace was created concurrently; retry") from exc
    return user, workspace


def signup(
    session: Session,
    settings: Settings,
    *,
    email: str,
    display_name: str,
    password: str,
    workspace_name: str,
) -> tuple[User, Workspace]:
    """Self-service sign-up: always a new workspace, owned by the new user."""
    if not settings.auth_allow_signup:
        raise PermissionDeniedError(
            "sign-up is disabled on this deployment; ask a workspace owner to add you"
        )
    return create_user(
        session,
        settings,
        email=email,
        display_name=display_name,
        password=password,
        workspace_name=workspace_name,
        role=Role.OWNER,
        new_workspace=True,
    )


def login(session: Session, settings: Settings, *, email: str, password: str) -> IssuedSession:
    """Verify a password and open a session. Commits; refusals commit too."""
    now = utc_now()
    user = repo.get_user_by_email(session, normalise_email(email))
    if user is None:
        passwords.verify_password(password, _dummy_hash(settings.auth_password_hash_log2_n))
        raise UnauthenticatedError(LOGIN_FAILED)
    if user.locked_until is not None and user.locked_until > now:
        passwords.verify_password(password, _dummy_hash(settings.auth_password_hash_log2_n))
        raise UnauthenticatedError(LOGIN_FAILED)
    correct = passwords.verify_password(password, user.password_hash)
    if not correct or not user.is_active:
        if user.is_active:
            user.failed_login_attempts += 1
            if user.failed_login_attempts >= settings.auth_max_failed_logins:
                user.locked_until = now + timedelta(minutes=settings.auth_lockout_minutes)
                user.failed_login_attempts = 0
        session.commit()
        raise UnauthenticatedError(LOGIN_FAILED)

    user.failed_login_attempts = 0
    user.locked_until = None
    user.last_login_at = now
    if passwords.needs_rehash(user.password_hash, log2_n=settings.auth_password_hash_log2_n):
        user.password_hash = passwords.hash_password(
            password, log2_n=settings.auth_password_hash_log2_n
        )
    token = tokens.new_token()
    record = repo.add_session(
        session,
        user_id=user.id,
        token_hash=tokens.token_hash(token),
        now=now,
        expires_at=now + timedelta(hours=settings.auth_session_ttl_hours),
    )
    session.commit()
    return IssuedSession(token=token, record=record, user=user)


def resolve(session: Session, settings: Settings, token: str) -> Principal:
    """The principal behind a bearer token, or `UnauthenticatedError`.

    Touches `last_seen_at` at most once per `TOUCH_INTERVAL`, committing only
    then, so an authenticated read is not a write on every request.
    """
    if not tokens.well_formed(token):
        raise UnauthenticatedError(SESSION_INVALID)
    found = repo.get_session_and_user(session, tokens.token_hash(token))
    now = utc_now()
    if found is None or not _live(found[0], settings, now):
        raise UnauthenticatedError(SESSION_INVALID)
    record, user = found
    if not user.is_active:
        raise UnauthenticatedError(SESSION_INVALID)
    if now - record.last_seen_at >= TOUCH_INTERVAL:
        record.last_seen_at = now
        session.commit()
    return Principal(user.id, user.email, user.display_name, record.id)


def _live(record: AuthSession, settings: Settings, now: datetime) -> bool:
    idle = timedelta(minutes=settings.auth_session_idle_minutes)
    return (
        record.revoked_at is None and record.expires_at > now and record.last_seen_at + idle > now
    )


def logout(session: Session, principal: Principal) -> None:
    if principal.session_id is None:
        return
    record = session.get(AuthSession, principal.session_id)
    if record is not None and record.revoked_at is None:
        record.revoked_at = utc_now()
        session.commit()


def change_password(
    session: Session,
    settings: Settings,
    principal: Principal,
    *,
    current_password: str,
    new_password: str,
) -> int:
    """Change the password and revoke every other session. Returns how many."""
    user = repo.get_user(session, principal.user_id)
    if user is None or not passwords.verify_password(current_password, user.password_hash):
        raise UnauthenticatedError("current password is incorrect")
    _validate_new_password(new_password, user.email)
    user.password_hash = passwords.hash_password(
        new_password, log2_n=settings.auth_password_hash_log2_n
    )
    revoked = repo.revoke_sessions(session, user.id, now=utc_now(), keep=principal.session_id)
    session.commit()
    return revoked


__all__ = [
    "DEFAULT_PROJECT_NAME",
    "LOGIN_FAILED",
    "IssuedSession",
    "Principal",
    "add_new_workspace",
    "change_password",
    "create_user",
    "login",
    "logout",
    "normalise_email",
    "resolve",
    "signup",
    "slugify",
]
