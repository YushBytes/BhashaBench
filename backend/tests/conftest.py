"""Shared pytest fixtures."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import AppEnv, Settings, get_settings
from app.main import create_app


@pytest.fixture
def settings() -> Settings:
    """Deterministic settings for tests, independent of any local `.env`."""
    return Settings(
        app_env=AppEnv.TEST,
        app_version="0.1.0",
        secret_key="test-secret-key-not-used-for-anything",
        database_url="postgresql+psycopg://test:test@localhost:5432/test",
        _env_file=None,
    )


@pytest.fixture
def test_app(settings: Settings) -> FastAPI:
    """An application instance built against the test settings."""
    app = create_app(settings=settings)
    # Routes resolve settings via dependency injection; override it so they
    # see the same object the app was constructed with.
    app.dependency_overrides[get_settings] = lambda: settings
    return app


@pytest.fixture
def client(test_app: FastAPI) -> Iterator[TestClient]:
    """HTTP client that runs the app's lifespan, as a real server would."""
    with TestClient(test_app) as test_client:
        yield test_client
