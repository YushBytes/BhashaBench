"""Phase 14 part 2 HTTP hardening: the sliding-window limiter, API and login
rate limits through the real app, and the security headers."""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import AppEnv, Settings, get_settings
from app.core.security import SlidingWindowLimiter, security_headers
from app.db.session import get_db
from app.main import create_app
from app.services import auth_service
from tests.auth_helpers import PASSWORD
from tests.conftest import PRODUCTION_SAFE


class TestLimiter:
    def test_it_allows_up_to_the_limit_then_waits(self) -> None:
        now = [0.0]
        limiter = SlidingWindowLimiter(3, clock=lambda: now[0])
        assert [limiter.hit("k") for _ in range(3)] == [None, None, None]
        wait = limiter.hit("k")
        assert wait is not None and 59 <= wait <= 60
        now[0] = 61.0
        assert limiter.hit("k") is None

    def test_keys_are_independent(self) -> None:
        limiter = SlidingWindowLimiter(1)
        assert limiter.hit("a") is None and limiter.hit("b") is None
        assert limiter.hit("a") is not None

    def test_zero_disables(self) -> None:
        limiter = SlidingWindowLimiter(0)
        assert all(limiter.hit("k") is None for _ in range(1000))


def _app(settings: Settings, db_session: Session, **limits: object) -> FastAPI:
    configured = settings.model_copy(update=limits)
    app = create_app(settings=configured)
    app.dependency_overrides[get_settings] = lambda: configured

    def db() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = db
    return app


class TestRateLimits:
    def test_the_api_answers_429_with_retry_after(
        self, settings: Settings, db_session: Session
    ) -> None:
        with TestClient(_app(settings, db_session, rate_limit_requests_per_minute=3)) as client:
            codes = [client.get("/api/v1/languages").status_code for _ in range(4)]
            assert codes == [200, 200, 200, 429]
            limited = client.get("/api/v1/languages")
            assert limited.json()["error"]["type"] == "rate_limited"
            assert int(limited.headers["retry-after"]) >= 1

    def test_liveness_is_never_limited(self, settings: Settings, db_session: Session) -> None:
        with TestClient(_app(settings, db_session, rate_limit_requests_per_minute=1)) as client:
            assert {client.get("/health").status_code for _ in range(5)} == {200}

    def test_login_is_limited_per_email_whatever_the_address(
        self, settings: Settings, db_session: Session
    ) -> None:
        user, _ = auth_service.create_user(
            db_session, settings, email=f"rl-{uuid.uuid4().hex[:8]}@example.test",
            display_name="RL", password=PASSWORD, workspace_name=f"rl-{uuid.uuid4().hex[:8]}",
        )  # fmt: skip
        app = _app(settings, db_session, rate_limit_logins_per_minute=2, trust_forwarded_for=True)
        with TestClient(app) as client:
            codes = [
                client.post(
                    "/api/v1/auth/login",
                    json={"email": user.email, "password": "wrong guess"},
                    headers={"X-Forwarded-For": f"10.0.0.{i}"},
                ).status_code
                for i in range(3)
            ]
            assert codes == [401, 401, 429]
            # Even the right password waits: the limit is checked before verifying.
            right = client.post(
                "/api/v1/auth/login",
                json={"email": user.email, "password": PASSWORD},
                headers={"X-Forwarded-For": "10.0.0.99"},
            )
            assert right.status_code == 429

    def test_forwarded_for_is_ignored_unless_trusted(
        self, settings: Settings, db_session: Session
    ) -> None:
        with TestClient(_app(settings, db_session, rate_limit_requests_per_minute=2)) as client:
            codes = [
                client.get(
                    "/api/v1/languages", headers={"X-Forwarded-For": f"10.1.0.{i}"}
                ).status_code
                for i in range(3)
            ]
            assert codes == [200, 200, 429]  # one socket peer, whatever the header claims


class TestHeaders:
    def test_every_api_response_carries_them(self, client: TestClient) -> None:
        response = client.get("/api/v1/languages")
        for name, value in {
            "x-content-type-options": "nosniff",
            "x-frame-options": "DENY",
            "referrer-policy": "no-referrer",
            "content-security-policy": "default-src 'none'; frame-ancestors 'none'",
        }.items():
            assert response.headers[name] == value

    def test_errors_carry_them_too(self, client: TestClient) -> None:
        assert client.get("/api/v1/no-such-route").headers["x-frame-options"] == "DENY"

    def test_hsts_only_when_deployed(self) -> None:
        assert "Strict-Transport-Security" not in security_headers("/api/v1/x", deployed=False)
        assert (
            "max-age=" in security_headers("/api/v1/x", deployed=True)["Strict-Transport-Security"]
        )

    def test_the_docs_are_not_given_the_api_csp(self) -> None:
        assert "Content-Security-Policy" not in security_headers("/docs", deployed=False)

    def test_auth_responses_are_not_cached(self) -> None:
        assert security_headers("/api/v1/auth/me", deployed=False)["Cache-Control"] == "no-store"

    @pytest.mark.parametrize("env", [AppEnv.STAGING, AppEnv.PRODUCTION])
    def test_a_deployed_app_sends_hsts(self, env: AppEnv) -> None:
        app = create_app(
            settings=Settings(app_env=env, secret_key="x" * 40, _env_file=None, **PRODUCTION_SAFE)
        )
        with TestClient(app) as client:
            assert "strict-transport-security" in client.get("/health").headers
