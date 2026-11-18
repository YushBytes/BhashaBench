"""Workspaces, their members, and their projects.

Membership rules, enforced here rather than trusted to a client:

- a member is added by the email of an existing account; there is no
  invitation-by-email flow, because the application sends no email;
- `can_assign` decides who may grant, change or revoke which role, so an
  admin can never create an owner or an admin, nor touch one;
- a workspace always keeps at least one owner: demoting or removing the
  last one is a conflict, whoever asks;
- anyone may leave a workspace (remove themselves), subject to the
  last-owner rule.
"""

from __future__ import annotations

import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.permissions import Permission, can_assign
from app.models.identity import Project, Role, User, Workspace, WorkspaceMembership
from app.repositories import identity as repo
from app.repositories import suites as suite_repo
from app.services import access_service
from app.services.auth_service import (
    Principal,
    add_new_workspace,
    normalise_email,
)
from app.services.errors import ConflictError, NotFoundError, PermissionDeniedError


def _commit(session: Session, conflict: str) -> None:
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError(conflict) from exc


# -- Workspaces ---------------------------------------------------------------


def create_workspace(
    session: Session, principal: Principal, *, name: str, slug: str | None
) -> tuple[Workspace, Role]:
    workspace = add_new_workspace(session, name=name, slug=slug)
    repo.add_membership(
        session, workspace_id=workspace.id, user_id=principal.user_id, role=Role.OWNER
    )
    _commit(session, "the workspace was created concurrently; retry")
    return workspace, Role.OWNER


def list_workspaces(session: Session, principal: Principal) -> list[tuple[Workspace, Role]]:
    return [(w, m.role) for m, w in repo.memberships_of_user(session, principal.user_id)]


# -- Members ------------------------------------------------------------------


def list_members(
    session: Session, principal: Principal, workspace_id: uuid.UUID
) -> list[tuple[WorkspaceMembership, User]]:
    access_service.require_workspace(session, principal, workspace_id, Permission.VIEW)
    return repo.members_of_workspace(session, workspace_id)


def _target(session: Session, workspace_id: uuid.UUID, user_id: uuid.UUID) -> WorkspaceMembership:
    record = repo.membership(session, workspace_id, user_id)
    if record is None:
        raise NotFoundError("Member", user_id)
    return record


def _check_assign(actor: Role, current: Role | None, new: Role | None) -> None:
    if not can_assign(actor, current, new):

        def label(role: Role | None) -> str:
            return "none" if role is None else role.value

        raise PermissionDeniedError(
            f"role '{actor.value}' cannot change a member from '{label(current)}' to "
            f"'{label(new)}'; only an owner manages owners and admins"
        )


def _keep_an_owner(
    session: Session, workspace_id: uuid.UUID, current: Role, new: Role | None
) -> None:
    if (
        current is Role.OWNER
        and new is not Role.OWNER
        and repo.count_owners(session, workspace_id) <= 1
    ):
        raise ConflictError("a workspace must keep at least one owner; appoint another first")


def add_member(
    session: Session, principal: Principal, workspace_id: uuid.UUID, *, email: str, role: Role
) -> tuple[WorkspaceMembership, User]:
    _, actor = access_service.require_workspace(
        session, principal, workspace_id, Permission.MANAGE_MEMBERS
    )
    _check_assign(actor, None, role)
    user = repo.get_user_by_email(session, normalise_email(email))
    if user is None:
        raise NotFoundError("User", normalise_email(email))
    if repo.membership(session, workspace_id, user.id) is not None:
        raise ConflictError(f"'{user.email}' is already a member")
    record = repo.add_membership(session, workspace_id=workspace_id, user_id=user.id, role=role)
    _commit(session, f"'{user.email}' is already a member")
    return record, user


def change_role(
    session: Session, principal: Principal, workspace_id: uuid.UUID, user_id: uuid.UUID, role: Role
) -> tuple[WorkspaceMembership, User]:
    _, actor = access_service.require_workspace(
        session, principal, workspace_id, Permission.MANAGE_MEMBERS
    )
    record = _target(session, workspace_id, user_id)
    user = repo.get_user(session, user_id)
    assert user is not None  # the membership's foreign key guarantees it
    if record.role is role:
        return record, user
    _check_assign(actor, record.role, role)
    _keep_an_owner(session, workspace_id, record.role, role)
    record.role = role
    session.commit()
    return record, user


def remove_member(
    session: Session, principal: Principal, workspace_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    if user_id == principal.user_id:
        # Leaving: any member may, which is why this checks VIEW, not MANAGE.
        access_service.require_workspace(session, principal, workspace_id, Permission.VIEW)
        record = _target(session, workspace_id, user_id)
    else:
        _, actor = access_service.require_workspace(
            session, principal, workspace_id, Permission.MANAGE_MEMBERS
        )
        record = _target(session, workspace_id, user_id)
        _check_assign(actor, record.role, None)
    _keep_an_owner(session, workspace_id, record.role, None)
    session.delete(record)
    session.commit()


# -- Projects -----------------------------------------------------------------


def list_projects(session: Session, principal: Principal, workspace_id: uuid.UUID) -> list[Project]:
    access_service.require_workspace(session, principal, workspace_id, Permission.VIEW)
    return repo.projects_of_workspace(session, workspace_id)


def create_project(
    session: Session,
    principal: Principal,
    workspace_id: uuid.UUID,
    *,
    name: str,
    description: str | None,
) -> Project:
    access_service.require_workspace(session, principal, workspace_id, Permission.MANAGE_PROJECTS)
    name = name.strip()
    if repo.get_project_by_name(session, workspace_id, name) is not None:
        raise ConflictError(f"a project named '{name}' already exists in this workspace")
    project = repo.add_project(
        session, workspace_id=workspace_id, name=name, description=description
    )
    _commit(session, f"a project named '{name}' already exists in this workspace")
    return project


def get_project(session: Session, principal: Principal, project_id: uuid.UUID) -> Project:
    project, _ = access_service.require_project(session, principal, project_id, Permission.VIEW)
    return project


def update_project(
    session: Session,
    principal: Principal,
    project_id: uuid.UUID,
    *,
    name: str | None,
    description: str | None,
    description_set: bool,
) -> Project:
    project, _ = access_service.require_project(
        session, principal, project_id, Permission.MANAGE_PROJECTS
    )
    if name is not None and name.strip() != project.name:
        existing = repo.get_project_by_name(session, project.workspace_id, name.strip())
        if existing is not None:
            raise ConflictError(
                f"a project named '{name.strip()}' already exists in this workspace"
            )
        project.name = name.strip()
    if description_set:
        project.description = description
    _commit(session, "a project with that name already exists in this workspace")
    return project


def delete_project(session: Session, principal: Principal, project_id: uuid.UUID) -> None:
    """Delete an empty project. One holding suites is refused, never cascaded:
    the suites carry recorded runs, and the database's RESTRICT agrees."""
    project, _ = access_service.require_project(
        session, principal, project_id, Permission.MANAGE_PROJECTS
    )
    suites = suite_repo.count_in_project(session, project_id)
    if suites:
        raise ConflictError(
            f"project '{project.name}' still holds {suites} suite(s); delete them first"
        )
    session.delete(project)
    session.commit()


__all__ = [
    "add_member",
    "change_role",
    "create_project",
    "create_workspace",
    "delete_project",
    "get_project",
    "list_members",
    "list_projects",
    "list_workspaces",
    "remove_member",
    "update_project",
]
