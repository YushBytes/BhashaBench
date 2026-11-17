"""Workspaces, members and projects (Phase 14).

A workspace the caller does not belong to is a 404, never a 403: its
existence is not disclosed. A member whose role is too low gets a 403 that
names the role and the permission. See docs/AUTH.md for the matrix.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Response, status

from app.api.deps import CurrentPrincipal, DbSession
from app.auth.permissions import Permission
from app.models.identity import Project, User, WorkspaceMembership
from app.schemas.auth import (
    MemberAdd,
    MemberRead,
    MemberUpdate,
    ProjectCreate,
    ProjectRead,
    ProjectUpdate,
    WorkspaceCreate,
    WorkspaceRead,
)
from app.schemas.common import ErrorResponse
from app.services import access_service, workspace_service

router = APIRouter(tags=["workspaces"])

_ERRORS = {
    status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse},
    status.HTTP_403_FORBIDDEN: {"model": ErrorResponse},
    status.HTTP_404_NOT_FOUND: {"model": ErrorResponse},
    status.HTTP_409_CONFLICT: {"model": ErrorResponse},
}


def _project(project: Project) -> ProjectRead:
    return ProjectRead(
        id=project.id,
        workspace_id=project.workspace_id,
        name=project.name,
        description=project.description,
        created_at=project.created_at,
    )


def _member(record: WorkspaceMembership, user: User) -> MemberRead:
    return MemberRead(
        user_id=user.id, email=user.email, display_name=user.display_name, role=record.role
    )


@router.get("/workspaces", summary="Workspaces the caller belongs to", responses=_ERRORS)
def list_workspaces(principal: CurrentPrincipal, session: DbSession) -> list[WorkspaceRead]:
    return [
        WorkspaceRead(id=w.id, name=w.name, slug=w.slug, role=role, created_at=w.created_at)
        for w, role in workspace_service.list_workspaces(session, principal)
    ]


@router.post(
    "/workspaces",
    status_code=status.HTTP_201_CREATED,
    summary="Create a workspace, owned by the caller, with a Default project",
    responses=_ERRORS,
)
def create_workspace(
    body: WorkspaceCreate, principal: CurrentPrincipal, session: DbSession
) -> WorkspaceRead:
    workspace, role = workspace_service.create_workspace(
        session, principal, name=body.name, slug=body.slug
    )
    return WorkspaceRead(
        id=workspace.id,
        name=workspace.name,
        slug=workspace.slug,
        role=role,
        created_at=workspace.created_at,
    )


@router.get("/workspaces/{workspace_id}", summary="One workspace", responses=_ERRORS)
def get_workspace(
    workspace_id: uuid.UUID, principal: CurrentPrincipal, session: DbSession
) -> WorkspaceRead:
    workspace, role = access_service.require_workspace(
        session, principal, workspace_id, Permission.VIEW
    )
    return WorkspaceRead(
        id=workspace.id,
        name=workspace.name,
        slug=workspace.slug,
        role=role,
        created_at=workspace.created_at,
    )


@router.get(
    "/workspaces/{workspace_id}/members", summary="Members and their roles", responses=_ERRORS
)
def list_members(
    workspace_id: uuid.UUID, principal: CurrentPrincipal, session: DbSession
) -> list[MemberRead]:
    return [
        _member(m, u) for m, u in workspace_service.list_members(session, principal, workspace_id)
    ]


@router.post(
    "/workspaces/{workspace_id}/members",
    status_code=status.HTTP_201_CREATED,
    summary="Add an existing account to the workspace",
    description=(
        "Admins add members and viewers; only an owner adds an admin or an owner. 404 if no "
        "account has that email - there is no email invitation, because the application "
        "sends no email."
    ),
    responses=_ERRORS,
)
def add_member(
    workspace_id: uuid.UUID, body: MemberAdd, principal: CurrentPrincipal, session: DbSession
) -> MemberRead:
    record, user = workspace_service.add_member(
        session, principal, workspace_id, email=body.email, role=body.role
    )
    return _member(record, user)


@router.patch(
    "/workspaces/{workspace_id}/members/{user_id}",
    summary="Change a member's role",
    description="The last owner cannot be demoted (409).",
    responses=_ERRORS,
)
def change_role(
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    body: MemberUpdate,
    principal: CurrentPrincipal,
    session: DbSession,
) -> MemberRead:
    return _member(
        *workspace_service.change_role(session, principal, workspace_id, user_id, body.role)
    )


@router.delete(
    "/workspaces/{workspace_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a member, or leave (your own user id)",
    description="Removing the last owner is refused (409).",
    responses=_ERRORS,
)
def remove_member(
    workspace_id: uuid.UUID, user_id: uuid.UUID, principal: CurrentPrincipal, session: DbSession
) -> Response:
    workspace_service.remove_member(session, principal, workspace_id, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/workspaces/{workspace_id}/projects", summary="Projects in a workspace", responses=_ERRORS
)
def list_projects(
    workspace_id: uuid.UUID, principal: CurrentPrincipal, session: DbSession
) -> list[ProjectRead]:
    return [_project(p) for p in workspace_service.list_projects(session, principal, workspace_id)]


@router.post(
    "/workspaces/{workspace_id}/projects",
    status_code=status.HTTP_201_CREATED,
    summary="Create a project (admin or owner)",
    responses=_ERRORS,
)
def create_project(
    workspace_id: uuid.UUID, body: ProjectCreate, principal: CurrentPrincipal, session: DbSession
) -> ProjectRead:
    return _project(
        workspace_service.create_project(
            session, principal, workspace_id, name=body.name, description=body.description
        )
    )


@router.get("/projects/{project_id}", summary="One project", responses=_ERRORS)
def get_project(
    project_id: uuid.UUID, principal: CurrentPrincipal, session: DbSession
) -> ProjectRead:
    return _project(workspace_service.get_project(session, principal, project_id))


@router.patch(
    "/projects/{project_id}", summary="Rename or describe a project (admin or owner)",
    responses=_ERRORS,
)  # fmt: skip
def update_project(
    project_id: uuid.UUID, body: ProjectUpdate, principal: CurrentPrincipal, session: DbSession
) -> ProjectRead:
    return _project(
        workspace_service.update_project(
            session,
            principal,
            project_id,
            name=body.name,
            description=body.description,
            description_set="description" in body.model_fields_set,
        )
    )


__all__ = ["router"]
