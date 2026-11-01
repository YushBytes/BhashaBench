"""Application configuration.

Settings are resolved from, in order of increasing precedence: the field
defaults below, a `.env` file at the repository root, and real process
environment variables. This lets Docker Compose and CI override anything
without a file on disk.

Only the settings that Phase 1 actually uses are modelled here. Credentials
for third-party providers (Gnani, Twilio) and the run-safety limits are
declared in `.env.example` so the configuration surface is visible, but they
are deliberately not fields yet: a setting that nothing reads is dead code,
and the request shapes those integrations need are not yet known.
"""

from __future__ import annotations

import os
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# `backend/app/core/config.py` -> repository root is four levels up.
REPO_ROOT: Path = Path(__file__).resolve().parents[3]

PLACEHOLDER_SECRET = "replace-with-a-generated-secret"


class AppEnv(StrEnum):
    """Deployment environment the process believes it is running in."""

    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"
    TEST = "test"


class Settings(BaseSettings):
    """Validated application settings."""

    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        # `.env.example` documents variables that later phases will consume;
        # ignoring unknown keys keeps a complete `.env` from breaking startup.
        extra="ignore",
    )

    # -- Identity -------------------------------------------------------------
    app_name: str = "BhashaBench"
    app_tagline: str = "Test your voice AI before India tests it for you."
    app_version: str = Field(default="0.1.0", description="Semantic version of the API.")
    app_env: AppEnv = AppEnv.DEVELOPMENT

    # -- Security -------------------------------------------------------------
    secret_key: str = Field(
        default=PLACEHOLDER_SECRET,
        min_length=8,
        description="Signing key. Must be overridden outside development.",
    )

    # -- Persistence ----------------------------------------------------------
    # Phase 1 does not open a connection; the URL is validated and surfaced so
    # that the Compose wiring can be verified before Phase 2 adds a session.
    database_url: str = Field(
        default="postgresql+psycopg://bhashabench:change-me@localhost:5432/bhashabench",
        description="SQLAlchemy-style database URL.",
    )

    # -- HTTP -----------------------------------------------------------------
    api_v1_prefix: str = "/api/v1"
    # `NoDecode` stops pydantic-settings from JSON-parsing the raw environment
    # value, which would fail before the validator below can split it.
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000"],
        description="Browser origins permitted to call the API.",
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors_origins(cls, value: object) -> object:
        """Accept a comma-separated string so the value is easy to set in a shell."""
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @model_validator(mode="after")
    def _reject_placeholder_secret_outside_development(self) -> Settings:
        """Fail fast rather than run a non-development deployment with a known key."""
        deployed = (AppEnv.PRODUCTION, AppEnv.STAGING)
        if self.app_env in deployed and self.secret_key == PLACEHOLDER_SECRET:
            raise ValueError(
                f"SECRET_KEY is still the placeholder value while APP_ENV="
                f"{self.app_env}. Generate one with: "
                'python -c "import secrets; print(secrets.token_urlsafe(48))"'
            )
        return self

    @property
    def is_production(self) -> bool:
        """True when the process should hide debugging affordances."""
        return self.app_env is AppEnv.PRODUCTION

    @property
    def docs_url(self) -> str | None:
        """Swagger UI path, disabled in production."""
        return None if self.is_production else "/docs"

    @property
    def redoc_url(self) -> str | None:
        """ReDoc path, disabled in production."""
        return None if self.is_production else "/redoc"

    @property
    def openapi_url(self) -> str | None:
        """OpenAPI schema path, disabled in production."""
        return None if self.is_production else "/openapi.json"


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings singleton.

    Cached so that the `.env` file is parsed once. Tests that need to vary the
    environment should patch variables and then call `get_settings.cache_clear()`.
    """
    return Settings()


def describe_environment() -> dict[str, str]:
    """Report which configuration sources were available, for health output.

    Intentionally returns no values - only whether a source exists - so that a
    health endpoint can never leak a credential.
    """
    return {
        "env_file": "present" if (REPO_ROOT / ".env").is_file() else "absent",
        "database_url": "configured" if os.getenv("DATABASE_URL") else "default",
    }
