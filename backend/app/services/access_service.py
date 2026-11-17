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

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.permissions import Permission, allows
from app.models.call_session import CallSession
from app.models.identity import Project, Role, Workspace
from app.models.scenario import Scenario
from app.models.suite import TestSuite
from app.models.test_run import TestRun
from app.repositories import identity as repo
from app.services.auth_service import Principal
from app.services.errors import InvalidRequestError, NotFoundError, PermissionDeniedError


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


def _require_via_project(
    session: Session,
    principal: Principal,
    project_id: uuid.UUID | None,
    permission: Permission,
    resource: str,
    identifier: uuid.UUID,
) -> Role:
    """The caller's role over a resource that belongs to `project_id`.

    A missing resource and a resource in a foreign workspace raise the same
    `NotFoundError`, with the resource's own name, so the two are
    indistinguishable to the caller.
    """
    project = None if project_id is None else repo.get_project(session, project_id)
    role = None if project is None else role_in(session, principal, project.workspace_id)
    if role is None:
        raise NotFoundError(resource, identifier)
    if not allows(role, permission):
        raise _deny(role, permission)
    return role


def require_suite(
    session: Session, principal: Principal, suite_id: uuid.UUID, permission: Permission
) -> TestSuite:
    suite = session.get(TestSuite, suite_id)
    _require_via_project(
        session, principal, None if suite is None else suite.project_id, permission,
        "suite", suite_id,
    )  # fmt: skip
    assert suite is not None
    return suite


def _project_of(session: Session, statement: object) -> uuid.UUID | None:
    return session.scalar(statement)  # type: ignore[arg-type]


def require_scenario(
    session: Session, principal: Principal, scenario_id: uuid.UUID, permission: Permission
) -> uuid.UUID:
    """Check access to a scenario; returns its suite id."""
    row = session.execute(
        select(Scenario.suite_id, TestSuite.project_id)
        .join(TestSuite, TestSuite.id == Scenario.suite_id)
        .where(Scenario.id == scenario_id)
    ).first()
    _require_via_project(
        session, principal, None if row is None else row.project_id, permission,
        "scenario", scenario_id,
    )  # fmt: skip
    assert row is not None
    return row.suite_id


def require_run(
    session: Session, principal: Principal, run_id: uuid.UUID, permission: Permission
) -> None:
    project_id = _project_of(
        session,
        select(TestSuite.project_id)
        .join(TestRun, TestRun.suite_id == TestSuite.id)
        .where(TestRun.id == run_id),
    )
    _require_via_project(session, principal, project_id, permission, "TestRun", run_id)


def require_conversation(
    session: Session, principal: Principal, conversation_id: uuid.UUID, permission: Permission
) -> None:
    project_id = _project_of(
        session,
        select(TestSuite.project_id)
        .join(TestRun, TestRun.suite_id == TestSuite.id)
        .join(CallSession, CallSession.test_run_id == TestRun.id)
        .where(CallSession.id == conversation_id),
    )
    _require_via_project(
        session, principal, project_id, permission, "Conversation", conversation_id
    )


def require_run_target(
    session: Session, principal: Principal, suite_id: uuid.UUID, scenario_id: uuid.UUID
) -> None:
    """A new run or conversation: edit rights on the suite, and the scenario
    must be that suite's own.

    Without the second check a member could open a run in their own suite
    against another tenant's scenario id and read it back through the run's
    report - so a scenario from elsewhere is refused even when it is visible.
    """
    require_suite(session, principal, suite_id, Permission.EDIT)
    scenario_suite = require_scenario(session, principal, scenario_id, Permission.VIEW)
    if scenario_suite != suite_id:
        raise InvalidRequestError(
            f"scenario {scenario_id} belongs to another suite; a run uses its own suite's scenario"
        )


def editable_project(
    session: Session, principal: Principal, project_id: uuid.UUID | None
) -> uuid.UUID:
    """The project a new suite goes into.

    Named explicitly, it must be one the caller may edit. Omitted, it is
    inferred only when the caller can edit exactly one project - never
    guessed between several, because a suite created in the wrong workspace
    is visible to the wrong people.
    """
    if project_id is not None:
        require_project(session, principal, project_id, Permission.EDIT)
        return project_id
    editable = visible_project_ids(session, principal, Permission.EDIT)
    if len(editable) == 1:
        return editable[0]
    raise InvalidRequestError(
        "project_id is required: you can create suites in "
        f"{len(editable)} projects, so the target cannot be inferred"
        if editable
        else "you cannot create suites in any project; ask a workspace admin for the member role"
    )


__all__ = [
    "editable_project",
    "require_conversation",
    "require_project",
    "require_run",
    "require_run_target",
    "require_scenario",
    "require_suite",
    "require_workspace",
    "role_in",
    "visible_project_ids",
]
