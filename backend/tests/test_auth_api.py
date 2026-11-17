"""Phase 14 authentication through the real routes and PostgreSQL: sign-up,
login, logout, sessions, lockout, password change, cookie attributes, CSRF
origin checks, credential hygiene, and the `users create` CLI."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from typing import ClassVar

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from app.api.deps import SESSION_COOKIE
from app.auth import tokens
from app.cli import app as cli_app
from app.core.config import Settings
from app.models import AuthSession, Project, Role, User, WorkspaceMembership
from app.services import auth_service
from app.utils.timing import utc_now

AUTH = "/api/v1/auth"
PASSWORD = "a long enough passphrase"


@pytest.fixture
def account(db_session: Session, settings: Settings) -> User:
    user, _ = auth_service.create_user(
        db_session,
        settings,
        email=f"Person-{uuid.uuid4().hex[:8]}@Example.test",
        display_name="Person",
        password=PASSWORD,
        workspace_name=f"team-{uuid.uuid4().hex[:8]}",
    )
    return user


def _bearer(api_client: TestClient, email: str, password: str = PASSWORD) -> str:
    response = api_client.post(
        f"{AUTH}/login", json={"email": email, "password": password, "session_type": "bearer"}
    )
    assert response.status_code == 200, response.text
    return response.json()["token"]


class TestLogin:
    def test_bearer_login_returns_a_token_once_and_sets_no_cookie(
        self, api_client: TestClient, account: User
    ) -> None:
        response = api_client.post(
            f"{AUTH}/login",
            json={"email": account.email, "password": PASSWORD, "session_type": "bearer"},
        )
        assert response.status_code == 200
        body = response.json()
        assert tokens.well_formed(body["token"])
        assert SESSION_COOKIE not in response.cookies
        assert body["user"]["email"] == account.email

    def test_cookie_login_sets_a_hardened_cookie_and_returns_no_token(
        self, api_client: TestClient, account: User
    ) -> None:
        response = api_client.post(
            f"{AUTH}/login", json={"email": account.email, "password": PASSWORD}
        )
        assert response.status_code == 200
        assert response.json()["token"] is None
        header = response.headers["set-cookie"].lower()
        for attribute in ("httponly", "samesite=strict", "path=/", "max-age=43200"):
            assert attribute in header, attribute
        assert "secure" not in header  # APP_ENV=test serves http://; staging adds it

    def test_the_cookie_is_secure_when_deployed(self) -> None:
        deployed = Settings(app_env="staging", secret_key="x" * 40, _env_file=None)
        assert deployed.auth_cookie_secure is True

    def test_email_is_case_and_whitespace_insensitive(
        self, api_client: TestClient, account: User
    ) -> None:
        assert account.email == account.email.lower()
        _bearer(api_client, f"  {account.email.upper()} ")

    @pytest.mark.parametrize("which", ["unknown", "wrong", "inactive"])
    def test_every_failure_is_the_same_401(
        self, api_client: TestClient, db_session: Session, account: User, which: str
    ) -> None:
        email, password = account.email, PASSWORD
        if which == "unknown":
            email = "nobody@example.test"
        elif which == "wrong":
            password = "not the passphrase"
        else:
            account.is_active = False
            db_session.flush()
        response = api_client.post(f"{AUTH}/login", json={"email": email, "password": password})
        assert response.status_code == 401
        assert response.json()["error"]["message"] == auth_service.LOGIN_FAILED
        assert response.headers["www-authenticate"] == "Bearer"

    def test_repeated_failures_lock_the_account_even_against_the_right_password(
        self, api_client: TestClient, db_session: Session, account: User, settings: Settings
    ) -> None:
        for _ in range(settings.auth_max_failed_logins):
            api_client.post(f"{AUTH}/login", json={"email": account.email, "password": "wrong one"})
        db_session.refresh(account)
        assert account.locked_until is not None
        response = api_client.post(
            f"{AUTH}/login", json={"email": account.email, "password": PASSWORD}
        )
        assert response.status_code == 401
        account.locked_until = utc_now() - timedelta(seconds=1)
        db_session.flush()
        assert (
            api_client.post(
                f"{AUTH}/login", json={"email": account.email, "password": PASSWORD}
            ).status_code
            == 200
        )

    def test_a_success_resets_the_failure_count(
        self, api_client: TestClient, db_session: Session, account: User
    ) -> None:
        api_client.post(f"{AUTH}/login", json={"email": account.email, "password": "wrong one"})
        _bearer(api_client, account.email)
        db_session.refresh(account)
        assert account.failed_login_attempts == 0
        assert account.last_login_at is not None

    def test_a_weaker_stored_hash_is_upgraded_on_login(
        self, api_client: TestClient, db_session: Session, account: User, settings: Settings
    ) -> None:
        from app.auth.passwords import hash_password

        account.password_hash = hash_password(
            PASSWORD, log2_n=settings.auth_password_hash_log2_n + 1
        )
        db_session.flush()
        _bearer(api_client, account.email)
        db_session.refresh(account)
        assert account.password_hash.split("$")[1] == str(settings.auth_password_hash_log2_n)


class TestSessions:
    def test_me_requires_a_session(self, api_client: TestClient) -> None:
        response = api_client.get(f"{AUTH}/me")
        assert response.status_code == 401
        assert response.json()["error"]["type"] == "unauthenticated"

    def test_me_lists_the_workspaces_and_roles(self, api_client: TestClient, account: User) -> None:
        token = _bearer(api_client, account.email)
        body = api_client.get(f"{AUTH}/me", headers={"Authorization": f"Bearer {token}"}).json()
        assert body["user"]["id"] == str(account.id)
        assert [w["role"] for w in body["workspaces"]] == ["owner"]
        assert body["session_expires_at"] is not None

    @pytest.mark.parametrize(
        "header",
        ["Bearer", "Basic dXNlcjpwYXNz", "Bearer not-a-token", f"Bearer {tokens.new_token()}"],
    )
    def test_malformed_or_unknown_credentials_are_401(
        self, api_client: TestClient, header: str
    ) -> None:
        assert api_client.get(f"{AUTH}/me", headers={"Authorization": header}).status_code == 401

    def test_only_the_digest_is_stored(
        self, api_client: TestClient, db_session: Session, account: User
    ) -> None:
        token = _bearer(api_client, account.email)
        stored = db_session.scalars(
            select(AuthSession.token_hash).where(AuthSession.user_id == account.id)
        ).all()
        assert stored == [tokens.token_hash(token)]

    def test_logout_revokes_the_session(self, api_client: TestClient, account: User) -> None:
        headers = {"Authorization": f"Bearer {_bearer(api_client, account.email)}"}
        assert api_client.post(f"{AUTH}/logout", headers=headers).status_code == 204
        assert api_client.get(f"{AUTH}/me", headers=headers).status_code == 401

    @pytest.mark.parametrize("expiry", ["absolute", "idle", "revoked"])
    def test_an_expired_session_is_refused(
        self,
        api_client: TestClient,
        db_session: Session,
        account: User,
        settings: Settings,
        expiry: str,
    ) -> None:
        token = _bearer(api_client, account.email)
        record = db_session.scalar(
            select(AuthSession).where(AuthSession.token_hash == tokens.token_hash(token))
        )
        assert record is not None
        if expiry == "absolute":
            record.created_at = utc_now() - timedelta(hours=settings.auth_session_ttl_hours + 2)
            record.expires_at = utc_now() - timedelta(seconds=1)
        elif expiry == "idle":
            record.last_seen_at = utc_now() - timedelta(
                minutes=settings.auth_session_idle_minutes + 1
            )
        else:
            record.revoked_at = utc_now()
        db_session.flush()
        assert (
            api_client.get(f"{AUTH}/me", headers={"Authorization": f"Bearer {token}"}).status_code
            == 401
        )

    def test_a_deactivated_users_sessions_stop_working(
        self, api_client: TestClient, db_session: Session, account: User
    ) -> None:
        headers = {"Authorization": f"Bearer {_bearer(api_client, account.email)}"}
        account.is_active = False
        db_session.flush()
        assert api_client.get(f"{AUTH}/me", headers=headers).status_code == 401

    def test_activity_is_recorded_at_most_once_a_minute(
        self, api_client: TestClient, db_session: Session, account: User
    ) -> None:
        token = _bearer(api_client, account.email)
        headers = {"Authorization": f"Bearer {token}"}
        record = db_session.scalar(
            select(AuthSession).where(AuthSession.token_hash == tokens.token_hash(token))
        )
        assert record is not None
        first = record.last_seen_at
        api_client.get(f"{AUTH}/me", headers=headers)
        db_session.refresh(record)
        assert record.last_seen_at == first
        record.last_seen_at = first - timedelta(minutes=5)
        db_session.flush()
        api_client.get(f"{AUTH}/me", headers=headers)
        db_session.refresh(record)
        assert record.last_seen_at > first - timedelta(minutes=5)


class TestCookieCsrf:
    def _cookie_client(self, api_client: TestClient, account: User) -> TestClient:
        api_client.post(f"{AUTH}/login", json={"email": account.email, "password": PASSWORD})
        assert api_client.cookies.get(SESSION_COOKIE)
        return api_client

    def test_the_cookie_authenticates_reads(self, api_client: TestClient, account: User) -> None:
        client = self._cookie_client(api_client, account)
        assert client.get(f"{AUTH}/me").status_code == 200

    def test_a_foreign_origin_cannot_write_with_the_cookie(
        self, api_client: TestClient, account: User
    ) -> None:
        client = self._cookie_client(api_client, account)
        response = client.post(f"{AUTH}/logout", headers={"Origin": "https://evil.example"})
        assert response.status_code == 403
        assert client.get(f"{AUTH}/me").status_code == 200  # still signed in
        assert client.post(f"{AUTH}/logout", headers={"Origin": "null"}).status_code == 403

    def test_an_allowed_origin_can_write(self, api_client: TestClient, account: User) -> None:
        client = self._cookie_client(api_client, account)
        response = client.post(f"{AUTH}/logout", headers={"Origin": "http://localhost:3000"})
        assert response.status_code == 204
        assert client.get(f"{AUTH}/me").status_code == 401

    def test_logout_clears_the_cookie(self, api_client: TestClient, account: User) -> None:
        client = self._cookie_client(api_client, account)
        response = client.post(f"{AUTH}/logout")
        assert (
            'bb_session=""' in response.headers["set-cookie"]
            or "max-age=0" in response.headers["set-cookie"].lower()
        )


class TestPasswordChange:
    def test_changing_the_password_revokes_every_other_session(
        self, api_client: TestClient, account: User
    ) -> None:
        mine = {"Authorization": f"Bearer {_bearer(api_client, account.email)}"}
        other = {"Authorization": f"Bearer {_bearer(api_client, account.email)}"}
        response = api_client.post(
            f"{AUTH}/password",
            headers=mine,
            json={"current_password": PASSWORD, "new_password": "an entirely new passphrase"},
        )
        assert response.status_code == 200
        assert response.json() == {"other_sessions_revoked": 1}
        assert api_client.get(f"{AUTH}/me", headers=mine).status_code == 200
        assert api_client.get(f"{AUTH}/me", headers=other).status_code == 401
        _bearer(api_client, account.email, "an entirely new passphrase")

    def test_the_current_password_must_be_right(
        self, api_client: TestClient, account: User
    ) -> None:
        mine = {"Authorization": f"Bearer {_bearer(api_client, account.email)}"}
        response = api_client.post(
            f"{AUTH}/password",
            headers=mine,
            json={
                "current_password": "a wrong guess!",
                "new_password": "an entirely new passphrase",
            },
        )
        assert response.status_code == 401

    def test_a_weak_new_password_is_422(self, api_client: TestClient, account: User) -> None:
        mine = {"Authorization": f"Bearer {_bearer(api_client, account.email)}"}
        response = api_client.post(
            f"{AUTH}/password",
            headers=mine,
            json={"current_password": PASSWORD, "new_password": "short"},
        )
        assert response.status_code == 422
        assert "at least 12" in response.json()["error"]["message"]


class TestSignup:
    BODY: ClassVar[dict[str, str]] = {
        "email": "new@example.test",
        "display_name": "New",
        "password": PASSWORD,
        "workspace_name": "New Team",
    }

    def test_disabled_by_default(self, api_client: TestClient) -> None:
        response = api_client.post(f"{AUTH}/signup", json=self.BODY)
        assert response.status_code == 403
        assert "disabled" in response.json()["error"]["message"]

    def test_when_enabled_creates_an_owned_workspace_with_a_default_project(
        self, api_client: TestClient, db_session: Session, settings: Settings
    ) -> None:
        settings.auth_allow_signup = True
        response = api_client.post(f"{AUTH}/signup", json=self.BODY)
        assert response.status_code == 201, response.text
        user_id = uuid.UUID(response.json()["id"])
        membership = db_session.scalar(
            select(WorkspaceMembership).where(WorkspaceMembership.user_id == user_id)
        )
        assert membership is not None and membership.role is Role.OWNER
        projects = db_session.scalars(
            select(Project.name).where(Project.workspace_id == membership.workspace_id)
        ).all()
        assert projects == ["Default"]
        assert api_client.post(f"{AUTH}/signup", json=self.BODY).status_code == 409

    def test_a_weak_password_is_refused(self, api_client: TestClient, settings: Settings) -> None:
        settings.auth_allow_signup = True
        response = api_client.post(f"{AUTH}/signup", json={**self.BODY, "password": "short"})
        assert response.status_code == 422


class TestCredentialHygiene:
    def test_a_rejected_password_is_not_echoed_in_the_error(self, api_client: TestClient) -> None:
        secret = "S3cret-" + "x" * 1100
        response = api_client.post(f"{AUTH}/login", json={"email": "a@b.test", "password": secret})
        assert response.status_code == 422
        assert "S3cret-" not in response.text

    def test_no_password_or_token_reaches_the_logs(
        self, api_client: TestClient, account: User, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.DEBUG):
            token = _bearer(api_client, account.email)
            api_client.get(f"{AUTH}/me", headers={"Authorization": f"Bearer {token}"})
        assert PASSWORD not in caplog.text
        assert token not in caplog.text

    def test_the_password_is_not_in_the_request_model_repr(self) -> None:
        from app.schemas.auth import LoginRequest

        assert PASSWORD not in repr(LoginRequest(email="a@b.test", password=PASSWORD))

    def test_the_deployed_settings_refuse_a_lowered_hash_cost(self) -> None:
        with pytest.raises(ValueError, match="AUTH_PASSWORD_HASH_LOG2_N"):
            Settings(
                app_env="production",
                secret_key="x" * 40,
                auth_password_hash_log2_n=12,
                _env_file=None,
            )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@pytest.fixture
def cli_db(
    db_session: Session, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Session]:
    @contextmanager
    def scoped() -> Iterator[Session]:
        yield db_session

    monkeypatch.setattr("app.cli.main.session_scope", scoped)
    monkeypatch.setattr("app.cli.main.get_settings", lambda: settings)
    yield db_session


class TestUsersCreateCli:
    def test_creates_the_first_owner_and_their_workspace(self, cli_db: Session) -> None:
        result = CliRunner().invoke(
            cli_app,
            [
                "users",
                "create",
                "--email",
                "Owner@Example.test",
                "--workspace",
                "acme",
                "--password-stdin",
                "--json",
            ],
            input=PASSWORD + "\n",
        )
        assert result.exit_code == 0, result.output
        assert PASSWORD not in result.output
        user = cli_db.scalar(select(User).where(User.email == "owner@example.test"))
        assert user is not None

    def test_a_second_user_joins_the_existing_workspace(self, cli_db: Session) -> None:
        runner = CliRunner()
        base = ["users", "create", "--workspace", "acme", "--password-stdin"]
        assert (
            runner.invoke(cli_app, [*base, "--email", "a@example.test"], input=PASSWORD).exit_code
            == 0
        )
        result = runner.invoke(
            cli_app, [*base, "--email", "b@example.test", "--role", "viewer"], input=PASSWORD
        )
        assert result.exit_code == 0, result.output
        assert "viewer of acme" in result.output
        roles = cli_db.scalars(select(WorkspaceMembership.role)).all()
        assert sorted(roles) == sorted([Role.OWNER, Role.VIEWER])

    def test_a_weak_password_exits_2_and_a_duplicate_exits_1(self, cli_db: Session) -> None:
        runner = CliRunner()
        base = [
            "users",
            "create",
            "--email",
            "c@example.test",
            "--workspace",
            "acme",
            "--password-stdin",
        ]
        assert runner.invoke(cli_app, base, input="short").exit_code == 2
        assert runner.invoke(cli_app, base, input=PASSWORD).exit_code == 0
        assert runner.invoke(cli_app, base, input=PASSWORD).exit_code == 1

    def test_the_password_is_not_an_argument(self) -> None:
        result = CliRunner().invoke(
            cli_app,
            ["users", "create", "--email", "d@e.test", "--workspace", "w", "--password", "x"],
        )
        assert result.exit_code == 2
