"""Phase 14 identity primitives: password hashing, session tokens, the role
matrix, and the constraints the identity tables enforce in PostgreSQL."""

from __future__ import annotations

import hashlib
import uuid
from datetime import timedelta

import pytest
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm import Session

from app.auth import tokens
from app.auth.passwords import (
    MIN_PASSWORD_CHARS,
    hash_password,
    needs_rehash,
    password_problem,
    verify_password,
)
from app.auth.permissions import MINIMUM_ROLE, RANK, Permission, allows, can_assign
from app.models import AuthSession, Project, Role, User, Workspace, WorkspaceMembership
from app.utils.timing import utc_now

FAST = 10  # log2 N for tests; deployed settings refuse anything below 17


class TestPasswords:
    def test_round_trip(self) -> None:
        stored = hash_password("correct horse battery", log2_n=FAST)
        assert verify_password("correct horse battery", stored)
        assert not verify_password("correct horse batterz", stored)

    def test_the_hash_is_salted_and_self_describing(self) -> None:
        a, b = (hash_password("same password!", log2_n=FAST) for _ in range(2))
        assert a != b
        assert a.split("$")[:4] == ["scrypt", str(FAST), "8", "1"]
        assert "same password!" not in a

    def test_matches_the_scrypt_reference(self) -> None:
        """Independent recomputation from the stored salt, so the format and
        the KDF are what the docstring says and not merely self-consistent."""
        import base64

        stored = hash_password("reference pass", log2_n=FAST)
        _, n, r, p, salt, key = stored.split("$")
        expected = hashlib.scrypt(
            b"reference pass", salt=base64.b64decode(salt), n=1 << int(n), r=int(r), p=int(p),
            dklen=32,
        )  # fmt: skip
        assert base64.b64decode(key) == expected

    @pytest.mark.parametrize(
        "stored",
        ["", "plain", "bcrypt$10$8$1$AA==$AA==", "scrypt$99$8$1$AA==$AA==", "scrypt$x$8$1$a$b"],
    )
    def test_a_malformed_hash_verifies_false_not_raises(self, stored: str) -> None:
        assert verify_password("anything at all", stored) is False

    def test_an_oversized_password_is_refused_without_hashing(self) -> None:
        stored = hash_password("a reasonable one", log2_n=FAST)
        assert verify_password("x" * 5000, stored) is False
        with pytest.raises(ValueError):
            hash_password("x" * 5000, log2_n=FAST)

    def test_needs_rehash_when_the_cost_changes(self) -> None:
        stored = hash_password("rehash me please", log2_n=FAST)
        assert not needs_rehash(stored, log2_n=FAST)
        assert needs_rehash(stored, log2_n=FAST + 1)
        assert needs_rehash("garbage", log2_n=FAST)

    def test_policy_is_length_not_composition(self) -> None:
        assert password_problem("short") is not None
        assert password_problem("a" * MIN_PASSWORD_CHARS) is None
        assert password_problem(" " * 20) is not None
        assert password_problem("me@example.com.au", email="ME@example.com.au") is not None


class TestTokens:
    def test_tokens_are_unique_prefixed_and_well_formed(self) -> None:
        issued = {tokens.new_token() for _ in range(200)}
        assert len(issued) == 200
        assert all(t.startswith("bbs_") and tokens.well_formed(t) for t in issued)

    @pytest.mark.parametrize("bad", ["", "bbs_", "bbs_short", "xyz_" + "a" * 43, "bbs_" + "!" * 43])
    def test_malformed_tokens_are_rejected_before_lookup(self, bad: str) -> None:
        assert not tokens.well_formed(bad)

    def test_only_the_digest_is_derived(self) -> None:
        token = tokens.new_token()
        digest = tokens.token_hash(token)
        assert len(digest) == 64 and token not in digest


class TestRoleMatrix:
    def test_a_higher_role_holds_every_permission_of_a_lower_one(self) -> None:
        for permission in Permission:
            holders = [role for role in Role if allows(role, permission)]
            assert holders, permission
            least = min(holders, key=RANK.__getitem__)
            assert all(RANK[r] >= RANK[least] for r in holders)
            assert least is MINIMUM_ROLE[permission]

    def test_viewer_reads_only(self) -> None:
        assert [p for p in Permission if allows(Role.VIEWER, p)] == [Permission.VIEW]

    def test_member_cannot_delete_or_manage(self) -> None:
        assert allows(Role.MEMBER, Permission.EDIT)
        assert not allows(Role.MEMBER, Permission.DELETE)
        assert not allows(Role.MEMBER, Permission.MANAGE_MEMBERS)

    @pytest.mark.parametrize(
        ("actor", "current", "new", "expected"),
        [
            (Role.OWNER, None, Role.OWNER, True),
            (Role.OWNER, Role.ADMIN, None, True),
            (Role.ADMIN, None, Role.MEMBER, True),
            (Role.ADMIN, Role.VIEWER, Role.MEMBER, True),
            (Role.ADMIN, None, Role.ADMIN, False),
            (Role.ADMIN, Role.ADMIN, Role.MEMBER, False),
            (Role.ADMIN, Role.OWNER, None, False),
            (Role.MEMBER, None, Role.VIEWER, False),
            (Role.VIEWER, Role.VIEWER, None, False),
        ],
    )
    def test_assignment_never_reaches_above_the_actor(
        self, actor: Role, current: Role | None, new: Role | None, expected: bool
    ) -> None:
        assert can_assign(actor, current, new) is expected


# ---------------------------------------------------------------------------
# PostgreSQL constraints
# ---------------------------------------------------------------------------


def _user(session: Session, email: str = "") -> User:
    user = User(
        email=email or f"u{uuid.uuid4().hex[:10]}@example.test",
        display_name="Test User",
        password_hash=hash_password("not a real password", log2_n=FAST),
    )
    session.add(user)
    session.flush()
    return user


def _violates(session: Session, obj: object) -> None:
    savepoint = session.begin_nested()
    session.add(obj)
    # DataError too: an over-long value is refused by the column type before a
    # check constraint is consulted, and either is the database refusing it.
    with pytest.raises((IntegrityError, DataError)):
        session.flush()
    savepoint.rollback()


class TestIdentityStore:
    def test_email_is_unique_and_lower_case(self, db_session: Session) -> None:
        user = _user(db_session)
        _violates(db_session, User(email=user.email, display_name="x", password_hash="h"))
        _violates(db_session, User(email="Mixed@Example.test", display_name="x", password_hash="h"))
        _violates(db_session, User(email="no-at-sign", display_name="x", password_hash="h"))

    def test_session_stores_a_sha256_digest_only(self, db_session: Session) -> None:
        user = _user(db_session)
        now = utc_now()
        _violates(
            db_session,
            AuthSession(
                user_id=user.id,
                token_hash=tokens.new_token(),  # the raw token: wrong length
                expires_at=now + timedelta(hours=1),
                last_seen_at=now,
            ),
        )

    def test_membership_is_unique_per_workspace_and_role_is_checked(
        self, db_session: Session
    ) -> None:
        user = _user(db_session)
        workspace = Workspace(name="W", slug=f"w-{uuid.uuid4().hex[:8]}")
        db_session.add(workspace)
        db_session.flush()
        db_session.add(
            WorkspaceMembership(workspace_id=workspace.id, user_id=user.id, role=Role.OWNER)
        )
        db_session.flush()
        _violates(
            db_session,
            WorkspaceMembership(workspace_id=workspace.id, user_id=user.id, role=Role.VIEWER),
        )
        savepoint = db_session.begin_nested()
        from sqlalchemy import text

        with pytest.raises(IntegrityError):
            db_session.execute(
                text(
                    "INSERT INTO workspace_memberships (id, workspace_id, user_id, role) "
                    "VALUES (:id, :w, :u, 'root')"
                ),
                {"id": uuid.uuid4(), "w": workspace.id, "u": _user(db_session).id},
            )
        savepoint.rollback()

    @pytest.mark.parametrize("slug", ["Upper", "-leading", "has space", "a" * 64, ""])
    def test_workspace_slug_format(self, db_session: Session, slug: str) -> None:
        _violates(db_session, Workspace(name="W", slug=slug))

    def test_project_names_are_unique_per_workspace(self, db_session: Session) -> None:
        a = Workspace(name="A", slug=f"a-{uuid.uuid4().hex[:8]}")
        b = Workspace(name="B", slug=f"b-{uuid.uuid4().hex[:8]}")
        db_session.add_all([a, b])
        db_session.flush()
        db_session.add_all(
            [Project(workspace_id=a.id, name="P"), Project(workspace_id=b.id, name="P")]
        )
        db_session.flush()
        _violates(db_session, Project(workspace_id=a.id, name="P"))
        _violates(db_session, Project(workspace_id=a.id, name="   "))

    def test_deleting_a_user_removes_their_sessions_and_memberships(
        self, db_session: Session
    ) -> None:
        from sqlalchemy import func, select

        user = _user(db_session)
        workspace = Workspace(name="W", slug=f"w-{uuid.uuid4().hex[:8]}")
        db_session.add(workspace)
        db_session.flush()
        now = utc_now()
        db_session.add_all(
            [
                WorkspaceMembership(workspace_id=workspace.id, user_id=user.id, role=Role.MEMBER),
                AuthSession(
                    user_id=user.id,
                    token_hash=tokens.token_hash(tokens.new_token()),
                    expires_at=now + timedelta(hours=1),
                    last_seen_at=now,
                ),
            ]
        )
        db_session.flush()
        db_session.delete(user)
        db_session.flush()
        for model in (AuthSession, WorkspaceMembership):
            count = db_session.scalar(
                select(func.count()).select_from(model).where(model.user_id == user.id)
            )
            assert count == 0

    def test_a_workspace_with_projects_cannot_be_deleted(self, db_session: Session) -> None:
        from sqlalchemy import text

        workspace = Workspace(name="W", slug=f"w-{uuid.uuid4().hex[:8]}")
        db_session.add(workspace)
        db_session.flush()
        db_session.add(Project(workspace_id=workspace.id, name="P"))
        db_session.flush()
        savepoint = db_session.begin_nested()
        with pytest.raises(IntegrityError):
            db_session.execute(text("DELETE FROM workspaces WHERE id = :id"), {"id": workspace.id})
        savepoint.rollback()
