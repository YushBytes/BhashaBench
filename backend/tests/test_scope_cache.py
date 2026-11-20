"""The request-scoped project-role cache: faster, and never stale or shared.

`access_service` reads a caller's project roles once per request and keeps
them in the request's SQLAlchemy session. These tests hold one session open
across changes, which is harsher than production (where each request gets a
fresh session), and assert that every check still answers from the current
state of the database.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.auth.passwords import hash_password
from app.auth.permissions import Permission
from app.models.identity import Project, Role, User, Workspace, WorkspaceMembership
from app.models.suite import TestSuite as SuiteModel
from app.repositories import identity as identity_repo
from app.services import access_service
from app.services.auth_service import Principal
from app.services.errors import NotFoundError, PermissionDeniedError


def _user(session: Session) -> tuple[User, Principal]:
    tag = uuid.uuid4().hex[:8]
    user = User(
        id=uuid.uuid4(),
        email=f"scope-{tag}@example.test",
        display_name=f"Scope {tag}",
        password_hash=hash_password("scope cache test password", log2_n=10),
    )
    session.add(user)
    session.flush()
    return user, Principal(user.id, user.email, user.display_name, session_id=None)


@pytest.fixture
def tenancy(db_session: Session) -> dict:
    workspace = Workspace(id=uuid.uuid4(), name="Scope", slug=f"scope-{uuid.uuid4().hex[:8]}")
    project = Project(id=uuid.uuid4(), workspace_id=workspace.id, name="P")
    db_session.add_all([workspace, project])
    db_session.flush()
    suite = SuiteModel(name=f"scope-{uuid.uuid4().hex[:6]}", project_id=project.id)
    db_session.add(suite)
    viewer, viewer_p = _user(db_session)
    member, member_p = _user(db_session)
    db_session.add_all([
        WorkspaceMembership(workspace_id=workspace.id, user_id=viewer.id, role=Role.VIEWER),
        WorkspaceMembership(workspace_id=workspace.id, user_id=member.id, role=Role.MEMBER),
    ])  # fmt: skip
    db_session.flush()
    return {"workspace": workspace, "project": project, "suite": suite,
            "viewer": viewer_p, "member": member_p}  # fmt: skip


@pytest.fixture
def statements(db_session: Session) -> Iterator[list[str]]:
    seen: list[str] = []

    def count(conn: object, cursor: object, statement: str, *_: object) -> None:
        seen.append(statement)

    engine = db_session.get_bind()
    event.listen(engine, "before_cursor_execute", count)
    yield seen
    event.remove(engine, "before_cursor_execute", count)


class TestOnceARequest:
    def test_many_checks_read_the_roles_once(
        self, db_session: Session, tenancy: dict, statements: list[str]
    ) -> None:
        suite = tenancy["suite"]
        access_service.forget_roles(db_session)
        statements.clear()
        for _ in range(5):
            access_service.require_suite(db_session, tenancy["member"], suite.id, Permission.EDIT)
            access_service.visible_project_ids(db_session, tenancy["member"])
        role_reads = [s for s in statements if "workspace_memberships" in s]
        assert len(role_reads) == 1

    def test_two_callers_in_one_session_never_share_roles(
        self, db_session: Session, tenancy: dict
    ) -> None:
        suite = tenancy["suite"]
        access_service.require_suite(db_session, tenancy["member"], suite.id, Permission.EDIT)
        with pytest.raises(PermissionDeniedError):
            access_service.require_suite(db_session, tenancy["viewer"], suite.id, Permission.EDIT)
        _, outsider = _user(db_session)
        with pytest.raises(NotFoundError):
            access_service.require_suite(db_session, outsider, suite.id, Permission.VIEW)


class TestNeverStale:
    def test_a_promotion_takes_effect_on_the_next_check(
        self, db_session: Session, tenancy: dict
    ) -> None:
        suite, viewer = tenancy["suite"], tenancy["viewer"]
        with pytest.raises(PermissionDeniedError):
            access_service.require_suite(db_session, viewer, suite.id, Permission.EDIT)
        record = identity_repo.membership(db_session, tenancy["workspace"].id, viewer.user_id)
        assert record is not None
        record.role = Role.MEMBER
        db_session.flush()
        access_service.require_suite(db_session, viewer, suite.id, Permission.EDIT)

    def test_a_removal_takes_effect_on_the_next_check(
        self, db_session: Session, tenancy: dict
    ) -> None:
        suite, member = tenancy["suite"], tenancy["member"]
        access_service.require_suite(db_session, member, suite.id, Permission.VIEW)
        record = identity_repo.membership(db_session, tenancy["workspace"].id, member.user_id)
        db_session.delete(record)
        db_session.flush()
        with pytest.raises(NotFoundError):
            access_service.require_suite(db_session, member, suite.id, Permission.VIEW)
        assert tenancy["project"].id not in access_service.visible_project_ids(db_session, member)

    def test_a_new_project_is_visible_at_once(self, db_session: Session, tenancy: dict) -> None:
        member = tenancy["member"]
        before = access_service.visible_project_ids(db_session, member)
        extra = Project(id=uuid.uuid4(), workspace_id=tenancy["workspace"].id, name="Q")
        db_session.add(extra)
        db_session.flush()
        after = access_service.visible_project_ids(db_session, member)
        assert extra.id not in before and extra.id in after

    def test_a_rollback_forgets_what_it_undid(self, db_session: Session, tenancy: dict) -> None:
        suite, viewer = tenancy["suite"], tenancy["viewer"]
        savepoint = db_session.begin_nested()
        record = identity_repo.membership(db_session, tenancy["workspace"].id, viewer.user_id)
        record.role = Role.ADMIN
        db_session.flush()
        access_service.require_suite(db_session, viewer, suite.id, Permission.DELETE)
        savepoint.rollback()
        with pytest.raises(PermissionDeniedError):
            access_service.require_suite(db_session, viewer, suite.id, Permission.EDIT)


class TestFewerStatements:
    def test_an_authenticated_listing_spends_two_statements_on_identity_and_scope(
        self, api_client: TestClient, db_session: Session, statements: list[str]
    ) -> None:
        api_client.get("/api/v1/suites")
        # Tests share one session across requests; production opens a fresh
        # one per request, so start the measured request with no cache.
        access_service.forget_roles(db_session)
        statements.clear()
        assert api_client.get("/api/v1/suites").status_code == 200
        identity = [s for s in statements if "auth_sessions" in s or "FROM users" in s]
        scope = [s for s in statements if "workspace_memberships" in s]
        # Session and user in one join; roles once. Was three statements.
        assert (len(identity), len(scope)) == (1, 1), [" ".join(x.split())[:90] for x in statements]
