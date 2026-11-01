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

    def test_declares_the_phase_one_paths(self, client: TestClient) -> None:
        paths = client.get("/openapi.json").json()["paths"]

        assert set(paths) == {"/", "/health", "/api/v1/health"}

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
