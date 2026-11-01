"""Tests for the root, liveness and versioned health endpoints."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

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

        # The database component is honestly reported as not probed, so the
        # aggregate must be `degraded` rather than `ok`.
        assert body["status"] == "degraded"
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
        # Phase 1 opens no connection, so this must not claim to be healthy.
        assert by_name["database"]["status"] == "degraded"
        assert all(component["detail"] for component in components)

    def test_unversioned_api_health_is_not_served(self, client: TestClient) -> None:
        """Health detail lives behind the version prefix only."""
        assert client.get("/api/health").status_code == 404


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
