"""SQL for users, sessions, workspaces, memberships and projects. Never commits."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models.identity import AuthSession, Project, Role, User, Workspace, WorkspaceMembership

# -- Users --------------------------------------------------------------------


def get_user(session: Session, user_id: uuid.UUID) -> User | None:
    return session.get(User, user_id)


def get_user_by_email(session: Session, email: str) -> User | None:
    return session.scalar(select(User).where(User.email == email))


def add_user(session: Session, *, email: str, display_name: str, password_hash: str) -> User:
    user = User(email=email, display_name=display_name, password_hash=password_hash)
    session.add(user)
    session.flush()
    return user


# -- Sessions -----------------------------------------------------------------


def add_session(
    session: Session, *, user_id: uuid.UUID, token_hash: str, now: datetime, expires_at: datetime
) -> AuthSession:
    record = AuthSession(
        user_id=user_id,
        token_hash=token_hash,
        created_at=now,
        expires_at=expires_at,
        last_seen_at=now,
    )
    session.add(record)
    session.flush()
    return record


def get_session_by_hash(session: Session, token_hash: str) -> AuthSession | None:
    return session.scalar(select(AuthSession).where(AuthSession.token_hash == token_hash))


def get_session_and_user(session: Session, token_hash: str) -> tuple[AuthSession, User] | None:
    """A session and its user in one statement, for authenticating a request.

    Every authenticated request runs this, so it is one round trip rather
    than two: the load test found identity and scope to be most of an
    authenticated read's database time.
    """
    row = session.execute(
        select(AuthSession, User)
        .join(User, User.id == AuthSession.user_id)
        .where(AuthSession.token_hash == token_hash)
    ).first()
    return None if row is None else (row[0], row[1])


def revoke_sessions(
    session: Session, user_id: uuid.UUID, *, now: datetime, keep: uuid.UUID | None = None
) -> int:
    """Revoke every live session of a user, optionally sparing one."""
    statement = (
        update(AuthSession)
        .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    if keep is not None:
        statement = statement.where(AuthSession.id != keep)
    return session.execute(statement).rowcount or 0


# -- Workspaces and memberships ----------------------------------------------


def get_workspace(session: Session, workspace_id: uuid.UUID) -> Workspace | None:
    return session.get(Workspace, workspace_id)


def get_workspace_by_slug(session: Session, slug: str) -> Workspace | None:
    return session.scalar(select(Workspace).where(Workspace.slug == slug))


def add_workspace(session: Session, *, name: str, slug: str) -> Workspace:
    workspace = Workspace(name=name, slug=slug)
    session.add(workspace)
    session.flush()
    return workspace


def membership(
    session: Session, workspace_id: uuid.UUID, user_id: uuid.UUID
) -> WorkspaceMembership | None:
    return session.scalar(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.user_id == user_id,
        )
    )


def add_membership(
    session: Session, *, workspace_id: uuid.UUID, user_id: uuid.UUID, role: Role
) -> WorkspaceMembership:
    record = WorkspaceMembership(workspace_id=workspace_id, user_id=user_id, role=role)
    session.add(record)
    session.flush()
    return record


def memberships_of_user(
    session: Session, user_id: uuid.UUID
) -> list[tuple[WorkspaceMembership, Workspace]]:
    rows = session.execute(
        select(WorkspaceMembership, Workspace)
        .join(Workspace, Workspace.id == WorkspaceMembership.workspace_id)
        .where(WorkspaceMembership.user_id == user_id)
        .order_by(Workspace.name, Workspace.id)
    )
    return [(m, w) for m, w in rows]


def members_of_workspace(
    session: Session, workspace_id: uuid.UUID
) -> list[tuple[WorkspaceMembership, User]]:
    rows = session.execute(
        select(WorkspaceMembership, User)
        .join(User, User.id == WorkspaceMembership.user_id)
        .where(WorkspaceMembership.workspace_id == workspace_id)
        .order_by(User.email)
    )
    return [(m, u) for m, u in rows]


def count_owners(session: Session, workspace_id: uuid.UUID) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(WorkspaceMembership)
            .where(
                WorkspaceMembership.workspace_id == workspace_id,
                WorkspaceMembership.role == Role.OWNER,
            )
        )
        or 0
    )


# -- Projects -----------------------------------------------------------------


def get_project(session: Session, project_id: uuid.UUID) -> Project | None:
    return session.get(Project, project_id)


def get_project_by_name(session: Session, workspace_id: uuid.UUID, name: str) -> Project | None:
    return session.scalar(
        select(Project).where(Project.workspace_id == workspace_id, Project.name == name)
    )


def add_project(
    session: Session, *, workspace_id: uuid.UUID, name: str, description: str | None
) -> Project:
    project = Project(workspace_id=workspace_id, name=name, description=description)
    session.add(project)
    session.flush()
    return project


def projects_of_workspace(session: Session, workspace_id: uuid.UUID) -> list[Project]:
    return list(
        session.scalars(
            select(Project).where(Project.workspace_id == workspace_id).order_by(Project.name)
        )
    )


def project_roles(session: Session, user_id: uuid.UUID) -> dict[uuid.UUID, Role]:
    """Every project the user can reach, with their role in its workspace."""
    rows = session.execute(
        select(Project.id, WorkspaceMembership.role)
        .join(WorkspaceMembership, WorkspaceMembership.workspace_id == Project.workspace_id)
        .where(WorkspaceMembership.user_id == user_id)
    )
    return {row[0]: row[1] for row in rows}


__all__ = [
    "add_membership",
    "add_project",
    "add_session",
    "add_user",
    "add_workspace",
    "count_owners",
    "get_project",
    "get_project_by_name",
    "get_session_and_user",
    "get_session_by_hash",
    "get_user",
    "get_user_by_email",
    "get_workspace",
    "get_workspace_by_slug",
    "members_of_workspace",
    "membership",
    "memberships_of_user",
    "project_roles",
    "projects_of_workspace",
    "revoke_sessions",
]
