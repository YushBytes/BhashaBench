"""Application configuration.

Settings are resolved from, in order of increasing precedence: the field
defaults below, a `.env` file at the repository root, and real process
environment variables. This lets Docker Compose and CI override anything
without a file on disk.

Only settings that something actually reads are modelled here. A setting that
nothing consumes is dead code, so a variable stays in `.env.example` - where it
documents the configuration surface - until the phase that uses it arrives.
Phase 4 promotes the Gnani speech-to-text settings to real fields; Timbre
(Phase 5), Twilio (Phase 8) and the run-safety limits are still declared only
in `.env.example`.
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

# Duplicated from `app.transcription.providers.prisma_contract` on purpose:
# `app.core` is the base of the import graph and must not depend on a vendor
# adapter. The two are asserted equal by the test suite, so the duplication
# cannot drift silently.
PRISMA_DEFAULT_BASE_URL = "https://api.vachana.ai"
PRISMA_DEFAULT_MODEL = "prisma-v3.0"


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

    # -- Transcription (Phase 4) ---------------------------------------------
    # Only what the Prisma integration reads. Phase 5's Timbre settings and
    # Phase 8's Twilio settings stay in `.env.example` until their phase, for
    # the reason given in this module's docstring.
    transcription_provider: str = Field(
        default="fake",
        description=(
            "Which speech-to-text provider to use: 'prisma' or 'fake'. "
            "Defaults to the offline fake so a checkout with no credentials "
            "still starts and still runs its tests."
        ),
    )
    transcription_timeout_seconds: float = Field(
        default=30.0,
        gt=0,
        le=600,
        description="Per-request timeout for a provider call.",
    )
    transcription_max_attempts: int = Field(
        default=3,
        ge=1,
        le=10,
        description=(
            "Total attempts per batch transcription, including the first. "
            "1 disables retrying. Streaming is never retried automatically."
        ),
    )
    transcription_initial_backoff_seconds: float = Field(
        default=0.5, ge=0, le=60, description="First retry delay before jitter."
    )
    transcription_max_backoff_seconds: float = Field(
        default=8.0,
        ge=0,
        le=300,
        description="Ceiling on any retry delay, including a provider's Retry-After.",
    )
    transcription_max_upload_bytes: int = Field(
        default=10 * 1024 * 1024,
        gt=0,
        description=(
            "Largest audio payload accepted for batch transcription. The "
            "effective limit is the lower of this and the provider's own."
        ),
    )
    gnani_api_key: str = Field(
        default="",
        description=(
            "Gnani platform API key, sent as the X-API-Key-ID header. Empty by "
            "default: an unset credential must fail loudly at provider "
            "construction, not resolve to something that looks like a key."
        ),
    )
    gnani_api_base_url: str = Field(
        default=PRISMA_DEFAULT_BASE_URL,
        description="Gnani REST base URL. The documented default is api.vachana.ai.",
    )
    gnani_stt_model: str = Field(
        default=PRISMA_DEFAULT_MODEL,
        description="Prisma model identifier, e.g. 'prisma-v3.0'.",
    )
    transcription_live_tests: bool = Field(
        default=False,
        description=(
            "Opt in to tests that make real, billable provider calls. Off by "
            "default so CI can never spend money or need a credential."
        ),
    )

    @field_validator("transcription_provider", mode="before")
    @classmethod
    def _normalise_provider(cls, value: object) -> object:
        """Fold case and whitespace so `PRISMA` and ` prisma ` both work.

        Membership is not checked here: the registry owns the list of valid
        names, and duplicating it would let the two disagree.
        """
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("gnani_api_base_url", mode="before")
    @classmethod
    def _require_http_scheme(cls, value: object) -> object:
        """Reject a base URL that is not HTTP(S).

        The adapter derives its WebSocket URL from this value by swapping the
        scheme, so a malformed one breaks both transports. Catching it here
        turns a confusing connection error into a configuration error.
        """
        if isinstance(value, str) and value.strip():
            url = value.strip().rstrip("/")
            if not url.startswith(("http://", "https://")):
                raise ValueError(
                    f"GNANI_API_BASE_URL must start with http:// or https://, got '{url}'"
                )
            return url
        return value

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
