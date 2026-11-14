"""Tests for application metadata and the generated OpenAPI document."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import AppEnv, Settings
from app.main import create_app


class TestApplicationMetadata:
    """The app object must carry correct identity metadata."""

    def test_title_summary_and_version(self, test_app: FastAPI, settings: Settings) -> None:
        assert test_app.title == "BhashaBench"
        assert test_app.summary == "Test your voice AI before India tests it for you."
        assert test_app.version == settings.app_version

    def test_license_and_contact_are_declared(self, test_app: FastAPI) -> None:
        assert test_app.license_info is not None
        assert test_app.license_info["name"] == "MIT"
        assert test_app.contact is not None


class TestOpenApiDocument:
    """OpenAPI output must describe exactly the endpoints this phase ships."""

    def test_schema_is_served(self, client: TestClient) -> None:
        response = client.get("/openapi.json")

        assert response.status_code == 200
        assert response.json()["openapi"].startswith("3.")

    def test_declares_every_implemented_path(self, client: TestClient) -> None:
        """The documented surface must match exactly what is implemented.

        Phase 1 shipped three paths; Phase 2 added the suite and scenario
        endpoints; Phase 3 added library search, copy/move, bundle
        import/export and the language catalogue; Phase 4 added batch
        transcription and provider capabilities; Phase 5 added speech synthesis
        and its provider capabilities.

        Asserting the exact set - rather than a subset - is what catches a
        route added without being documented, or one left mounted after being
        removed.

        The transcription WebSocket at `/api/v1/transcription/stream` is
        deliberately absent: OpenAPI 3.1 has no way to describe a WebSocket,
        so it is documented in `docs/PROVIDERS.md` instead. A path appearing
        here that is not in that set is still a failure.
        """
        paths = client.get("/openapi.json").json()["paths"]

        assert set(paths) == {
            # Phase 1
            "/",
            "/health",
            "/api/v1/health",
            # Phase 2
            "/api/v1/suites",
            "/api/v1/suites/{suite_id}",
            "/api/v1/suites/{suite_id}/scenarios",
            "/api/v1/scenarios/validate",
            "/api/v1/scenarios/{scenario_id}",
            # Phase 3
            "/api/v1/languages",
            "/api/v1/scenarios",
            "/api/v1/scenarios/{scenario_id}/copy",
            "/api/v1/scenarios/{scenario_id}/move",
            "/api/v1/suites/{suite_id}/scenarios/import",
            "/api/v1/suites/{suite_id}/scenarios/export",
            # Phase 4
            "/api/v1/transcription",
            "/api/v1/transcription/providers",
            # Phase 5
            "/api/v1/speech/generate",
            "/api/v1/speech/providers",
            # Phase 6
            "/api/v1/caller/conversations",
            "/api/v1/caller/conversations/{conversation_id}",
            "/api/v1/caller/conversations/{conversation_id}/turns",
            "/api/v1/caller/conversations/{conversation_id}/bot-text",
            "/api/v1/caller/conversations/{conversation_id}/bot-audio",
            "/api/v1/caller/conversations/{conversation_id}/terminate",
            "/api/v1/caller/providers",
            # Phase 7
            "/api/v1/test-runs",
            "/api/v1/test-runs/{run_id}",
            "/api/v1/test-runs/{run_id}/start",
            "/api/v1/test-runs/{run_id}/bot-audio",
            "/api/v1/test-runs/{run_id}/bot-text",
            "/api/v1/test-runs/{run_id}/cancel",
            "/api/v1/test-runs/{run_id}/turns",
            "/api/v1/test-runs/{run_id}/artifacts",
            # Phase 8: the audio the inspector plays.
            "/api/v1/test-runs/{run_id}/artifacts/{turn_index}/audio",
            "/api/v1/test-runs/{run_id}/report",
            "/api/v1/test-runs/bot-adapters/available",
        }

    def test_info_block_matches_settings(self, client: TestClient, settings: Settings) -> None:
        info = client.get("/openapi.json").json()["info"]

        assert info["title"] == "BhashaBench"
        assert info["version"] == settings.app_version

    def test_response_models_are_referenced(self, client: TestClient) -> None:
        schemas = client.get("/openapi.json").json()["components"]["schemas"]

        assert {"ServiceIdentity", "HealthResponse", "ApiHealthResponse"} <= set(schemas)

    def test_swagger_ui_is_available(self, client: TestClient) -> None:
        assert client.get("/docs").status_code == 200


class TestApplicationFactory:
    """`create_app` must honour the settings it is given."""

    def test_production_app_hides_documentation(self) -> None:
        production_settings = Settings(
            app_env=AppEnv.PRODUCTION, secret_key="a-real-looking-secret", _env_file=None
        )

        app = create_app(settings=production_settings)

        with TestClient(app) as client:
            assert client.get("/docs").status_code == 404
            assert client.get("/openapi.json").status_code == 404
            # The service itself must still work.
            assert client.get("/health").json()["status"] == "ok"

    def test_each_call_returns_an_independent_app(self, settings: Settings) -> None:
        assert create_app(settings=settings) is not create_app(settings=settings)
