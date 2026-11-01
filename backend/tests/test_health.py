"""Tests for the root, liveness and versioned health endpoints."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_database_probe
from app.core.config import Settings


class TestRootEndpoint:
    """`GET /` must identify the service."""

    def test_returns_200(self, client: TestClient) -> None:
        assert client.get("/").status_code == 200

    def test_reports_service_identity(self, client: TestClient, settings: Settings) -> None:
        body = client.get("/").json()

        assert body["name"] == "BhashaBench"
        assert body["tagline"] == "Test your voice AI before India tests it for you."
        assert body["version"] == settings.app_version
        assert body["environment"] == "test"

    def test_does_not_leak_secrets(self, client: TestClient, settings: Settings) -> None:
        """The identity payload must never echo configuration secrets."""
        raw = client.get("/").text

        assert settings.secret_key not in raw
        assert settings.database_url not in raw


class TestLivenessEndpoint:
    """`GET /health` must be a cheap, stable liveness probe."""

    def test_returns_ok_status(self, client: TestClient, settings: Settings) -> None:
        response = client.get("/health")

        assert response.status_code == 200
        assert response.json() == {"status": "ok", "version": settings.app_version}


class TestApiHealthEndpoint:
    """`GET /api/v1/health` must return a structured report."""

    def test_returns_200(self, client: TestClient) -> None:
        assert client.get("/api/v1/health").status_code == 200

    def test_reports_aggregate_and_metadata(self, client: TestClient) -> None:
        body = client.get("/api/v1/health").json()

        # Phase 2 probes the database for real, and the `client` fixture
        # stubs that probe as reachable, so the aggregate is `ok`. In Phase 1
        # the database was never probed and this was `degraded`.
        assert body["status"] == "ok"
        assert body["service"] == "BhashaBench"
        assert body["api_version"] == "v1"
        assert body["environment"] == "test"

    def test_timestamp_is_utc_and_recent(self, client: TestClient) -> None:
        body = client.get("/api/v1/health").json()

        timestamp = datetime.fromisoformat(body["timestamp"])
        assert timestamp.tzinfo is not None
        assert abs((datetime.now(UTC) - timestamp).total_seconds()) < 60

    def test_uptime_is_non_negative(self, client: TestClient) -> None:
        assert client.get("/api/v1/health").json()["uptime_seconds"] >= 0

    def test_lists_expected_components(self, client: TestClient) -> None:
        components = client.get("/api/v1/health").json()["components"]
        by_name = {component["name"]: component for component in components}

        assert set(by_name) == {"api", "configuration", "database"}
        assert by_name["api"]["status"] == "ok"
        assert by_name["configuration"]["status"] == "ok"
        assert by_name["database"]["status"] == "ok"
        assert all(component["detail"] for component in components)

    def test_unversioned_api_health_is_not_served(self, client: TestClient) -> None:
        """Health detail lives behind the version prefix only."""
        assert client.get("/api/health").status_code == 404


class TestApiHealthDatabaseProbe:
    """The report must follow the probe, not assume a healthy database."""

    def test_unreachable_database_reports_unavailable(
        self, test_app: FastAPI, settings: Settings
    ) -> None:
        """Without the database nothing works, so `unavailable`, not `degraded`."""
        test_app.dependency_overrides[get_database_probe] = lambda: (
            lambda: (False, "Connection failed (OperationalError).")
        )

        with TestClient(test_app) as client:
            body = client.get("/api/v1/health").json()

        by_name = {component["name"]: component for component in body["components"]}
        assert by_name["database"]["status"] == "unavailable"
        assert body["status"] == "unavailable"

    def test_endpoint_still_answers_when_the_database_is_down(self, test_app: FastAPI) -> None:
        """A health endpoint that 500s when its dependency is down is useless."""
        test_app.dependency_overrides[get_database_probe] = lambda: (
            lambda: (False, "Connection failed (OperationalError).")
        )

        with TestClient(test_app) as client:
            assert client.get("/api/v1/health").status_code == 200

    def test_probe_detail_never_contains_the_connection_url(self, test_app: FastAPI) -> None:
        """The real probe reports only an exception class name, never the DSN."""
        with TestClient(test_app) as client:
            raw = client.get("/api/v1/health").text

        assert "postgresql" not in raw
        assert "password" not in raw.lower()

    def test_liveness_probe_is_independent_of_the_database(self, test_app: FastAPI) -> None:
        """`/health` must stay cheap so a load balancer keeps the pod alive."""
        test_app.dependency_overrides[get_database_probe] = lambda: (
            lambda: (False, "Connection failed (OperationalError).")
        )

        with TestClient(test_app) as client:
            response = client.get("/health")

        assert response.status_code == 200
        assert response.json()["status"] == "ok"


class TestErrorHandling:
    """Every error must use the uniform envelope."""

    def test_unknown_route_returns_error_envelope(self, client: TestClient) -> None:
        response = client.get("/does-not-exist")

        assert response.status_code == 404
        error = response.json()["error"]
        assert error["type"] == "not_found"
        assert error["status_code"] == 404
        assert error["message"]

    def test_wrong_method_returns_error_envelope(self, client: TestClient) -> None:
        response = client.post("/health")

        assert response.status_code == 405
        assert response.json()["error"]["type"] == "http_error"
