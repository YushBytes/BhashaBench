"""Tests for environment-based configuration loading and validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import PLACEHOLDER_SECRET, AppEnv, Settings, get_settings


class TestDefaults:
    """Settings must be usable with no environment at all."""

    def test_defaults_are_development_safe(self) -> None:
        settings = Settings(_env_file=None)

        assert settings.app_name == "BhashaBench"
        assert settings.app_env is AppEnv.DEVELOPMENT
        assert settings.api_v1_prefix == "/api/v1"
        assert settings.is_production is False

    def test_docs_are_enabled_outside_production(self) -> None:
        settings = Settings(app_env=AppEnv.DEVELOPMENT, _env_file=None)

        assert settings.docs_url == "/docs"
        assert settings.openapi_url == "/openapi.json"


class TestEnvironmentOverrides:
    """Real environment variables must take precedence over defaults."""

    def test_reads_values_from_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("APP_ENV", "staging")
        monkeypatch.setenv("APP_VERSION", "9.9.9")
        monkeypatch.setenv("SECRET_KEY", "a-real-looking-secret-value")

        settings = Settings(_env_file=None)

        assert settings.app_env is AppEnv.STAGING
        assert settings.app_version == "9.9.9"
        assert settings.secret_key == "a-real-looking-secret-value"

    def test_env_var_names_are_case_insensitive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("app_version", "1.2.3")

        assert Settings(_env_file=None).app_version == "1.2.3"

    def test_unknown_variables_are_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """`.env.example` declares future-phase variables; they must not break boot."""
        monkeypatch.setenv("MAX_CALLS_PER_RUN", "10")
        monkeypatch.setenv("NOISE_MASTER_SEED", "42")

        assert Settings(_env_file=None).app_name == "BhashaBench"

    def test_cors_origins_accept_comma_separated_string(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CORS_ORIGINS", "http://a.test, http://b.test")

        assert Settings(_env_file=None).cors_origins == ["http://a.test", "http://b.test"]


class TestValidation:
    """Invalid configuration must fail loudly at construction time."""

    def test_rejects_unknown_environment(self) -> None:
        with pytest.raises(ValidationError):
            Settings(app_env="not-an-environment", _env_file=None)

    def test_rejects_too_short_secret(self) -> None:
        with pytest.raises(ValidationError):
            Settings(secret_key="short", _env_file=None)

    @pytest.mark.parametrize("env", [AppEnv.PRODUCTION, AppEnv.STAGING])
    def test_rejects_placeholder_secret_outside_development(self, env: AppEnv) -> None:
        with pytest.raises(ValidationError, match="SECRET_KEY is still the placeholder"):
            Settings(app_env=env, secret_key=PLACEHOLDER_SECRET, _env_file=None)

    def test_allows_placeholder_secret_in_development(self) -> None:
        settings = Settings(
            app_env=AppEnv.DEVELOPMENT, secret_key=PLACEHOLDER_SECRET, _env_file=None
        )

        assert settings.secret_key == PLACEHOLDER_SECRET


class TestProductionBehaviour:
    """Production must hide debugging affordances."""

    def test_docs_are_disabled_in_production(self) -> None:
        settings = Settings(
            app_env=AppEnv.PRODUCTION, secret_key="a-real-looking-secret", _env_file=None
        )

        assert settings.is_production is True
        assert settings.docs_url is None
        assert settings.redoc_url is None
        assert settings.openapi_url is None


class TestSettingsCache:
    """`get_settings` is the cached process-wide accessor."""

    def test_returns_the_same_instance(self) -> None:
        assert get_settings() is get_settings()

    def test_cache_can_be_cleared(self, monkeypatch: pytest.MonkeyPatch) -> None:
        get_settings.cache_clear()
        monkeypatch.setenv("APP_VERSION", "7.7.7")
        try:
            assert get_settings().app_version == "7.7.7"
        finally:
            get_settings.cache_clear()
