"""Authorisation: may this principal do this to that resource?

Every check resolves a resource to its workspace and reads the caller's
membership there, then asks `app.auth.permissions.allows`. Two outcomes are
kept apart on purpose:

- **not a member of the workspace** -> `NotFoundError`, exactly as if the
  resource did not exist, so ids from another tenant cannot be probed;
- **a member without the role** -> `PermissionDeniedError` (403), because
  they can already see the resource and deserve to know why they may not
  change it.

Services and routes call these; nothing else decides access.
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.auth.permissions import Permission, allows
from app.models.identity import Project, Role, Workspace
from app.repositories import identity as repo
from app.services.auth_service import Principal
from app.services.errors import NotFoundError, PermissionDeniedError


def _deny(role: Role, permission: Permission) -> PermissionDeniedError:
    return PermissionDeniedError(
        f"your role '{role.value}' does not allow '{permission.value}' here"
    )


def role_in(session: Session, principal: Principal, workspace_id: uuid.UUID) -> Role | None:
    record = repo.membership(session, workspace_id, principal.user_id)
    return None if record is None else record.role


def require_workspace(
    session: Session, principal: Principal, workspace_id: uuid.UUID, permission: Permission
) -> tuple[Workspace, Role]:
    workspace = repo.get_workspace(session, workspace_id)
    role = None if workspace is None else role_in(session, principal, workspace_id)
    if workspace is None or role is None:
        raise NotFoundError("Workspace", workspace_id)
    if not allows(role, permission):
        raise _deny(role, permission)
    return workspace, role


def require_project(
    session: Session, principal: Principal, project_id: uuid.UUID, permission: Permission
) -> tuple[Project, Role]:
    project = repo.get_project(session, project_id)
    role = None if project is None else role_in(session, principal, project.workspace_id)
    if project is None or role is None:
        raise NotFoundError("Project", project_id)
    if not allows(role, permission):
        raise _deny(role, permission)
    return project, role


def visible_project_ids(
    session: Session, principal: Principal, permission: Permission = Permission.VIEW
) -> tuple[uuid.UUID, ...]:
    """Every project the principal holds `permission` in, for scoping listings."""
    return tuple(
        sorted(
            (pid for pid, role in repo.project_roles(session, principal.user_id).items()
             if allows(role, permission)),
            key=str,
        )
    )  # fmt: skip


__all__ = ["require_project", "require_workspace", "role_in", "visible_project_ids"]
