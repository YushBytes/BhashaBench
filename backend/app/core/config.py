"""Application configuration.

Settings are resolved from, in order of increasing precedence: the field
defaults below, a `.env` file at the repository root, and real process
environment variables. This lets Docker Compose and CI override anything
without a file on disk.

Only settings that something actually reads are modelled here. A setting that
nothing consumes is dead code, so a variable stays in `.env.example` - where it
documents the configuration surface - until the phase that uses it arrives.
Phase 4 promoted the Gnani speech-to-text settings to real fields and Phase 5
the text-to-speech ones; Twilio (Phase 9) and the run-safety limits are still
declared only in `.env.example`.
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

# Likewise duplicated from `app.speech.providers.timbre_contract`, and likewise
# asserted equal by the test suite so the duplication cannot drift.
TIMBRE_DEFAULT_MODEL = "timbre-v3.0"
TIMBRE_DEFAULT_VOICE = "Kalpana"


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
    # Phase 9's Twilio settings stay in `.env.example` until their phase, for
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

    # -- Speech synthesis (Phase 5) ------------------------------------------
    # No second credential: Gnani documents one key and one `X-API-Key-ID`
    # header across the platform, so Timbre reads `gnani_api_key` and
    # `gnani_api_base_url` above. A separate TTS key setting would be a
    # variable nobody could fill in.
    speech_provider: str = Field(
        default="fake",
        description=(
            "Which text-to-speech provider to use: 'timbre' or 'fake'. "
            "Defaults to the offline fake so a checkout with no credentials "
            "still starts and still runs its tests."
        ),
    )
    speech_timeout_seconds: float = Field(
        default=60.0,
        gt=0,
        le=600,
        description=(
            "Per-request timeout for a synthesis call. Higher than the "
            "transcription default: rendering a long utterance takes longer "
            "than recognising a short one."
        ),
    )
    speech_max_attempts: int = Field(
        default=3,
        ge=1,
        le=10,
        description=(
            "Total attempts per synthesis, including the first. 1 disables "
            "retrying. Only transient failures are retried; a 401, 402, 403 or "
            "a rejected parameter never is."
        ),
    )
    speech_initial_backoff_seconds: float = Field(
        default=0.5, ge=0, le=60, description="First retry delay before jitter."
    )
    speech_max_backoff_seconds: float = Field(
        default=8.0,
        ge=0,
        le=300,
        description="Ceiling on any retry delay, including a provider's Retry-After.",
    )
    speech_max_text_chars: int = Field(
        default=5000,
        gt=0,
        description=(
            "Longest text accepted for synthesis. BhashaBench's own bound - the "
            "provider publishes no limit of its own, so one request could "
            "otherwise cost an unbounded amount."
        ),
    )
    gnani_tts_model: str = Field(
        default=TIMBRE_DEFAULT_MODEL,
        description="Timbre model identifier, e.g. 'timbre-v3.0'.",
    )
    gnani_tts_voice: str = Field(
        default=TIMBRE_DEFAULT_VOICE,
        description=(
            "Default voice when a request names none. Sent explicitly rather "
            "than relying on an undeclared provider default, so a run stays "
            "reproducible."
        ),
    )
    speech_live_tests: bool = Field(
        default=False,
        description=(
            "Opt in to tests that make real, billable synthesis calls. Off by "
            "default, separately from the transcription flag, so enabling one "
            "does not silently enable the other."
        ),
    )

    # -- Simulated caller (Phase 6) ------------------------------------------
    # No credential of any kind: the only provider is a rule engine. Gnani Evon
    # is not integrated - see docs/PROVIDERS.md - so there is deliberately no
    # EVON_API_KEY here to suggest otherwise.
    caller_provider: str = Field(
        default="deterministic",
        description=(
            "Which caller strategy to use. Only 'deterministic' exists in this "
            "phase: a rule engine, not a language model."
        ),
    )
    caller_max_turns: int = Field(
        default=20,
        ge=2,
        le=100,
        description=(
            "Hard ceiling on conversation turns, applied on top of a "
            "scenario's own `goal.max_turns`. The lower of the two wins, so a "
            "scenario cannot ask for an unbounded conversation."
        ),
    )
    caller_max_clarifications: int = Field(
        default=2,
        ge=1,
        le=10,
        description=(
            "How many times the caller will press for a usable answer before "
            "closing the conversation as making no progress."
        ),
    )
    caller_max_message_chars: int = Field(
        default=600,
        ge=1,
        le=5000,
        description=(
            "Longest caller utterance accepted from a provider. Bounded "
            "independently of the speech limit so a runaway decision is caught "
            "before it reaches synthesis."
        ),
    )
    caller_turn_timeout_seconds: float = Field(
        default=90.0,
        gt=0,
        le=600,
        description="Ceiling on one full turn, including synthesis and transcription.",
    )
    caller_audio_storage_dir: str = Field(
        default="storage/caller-audio",
        description=(
            "Directory for conversation audio, relative to the repository root "
            "unless absolute. `storage/` is already git-ignored. Audio is kept "
            "on disk and only referenced from the database."
        ),
    )
    caller_synthesise_audio: bool = Field(
        default=False,
        description=(
            "Whether to synthesise caller audio for each turn. Off by default: "
            "with SPEECH_PROVIDER=timbre every turn becomes a billable call, so "
            "turning this on is a deliberate act."
        ),
    )

    # -- Pipeline (Phase 7) --------------------------------------------------

    pipeline_bot_adapter: str = Field(
        default="scripted",
        description=(
            "Which bot adapter a run uses by default. 'scripted' replays "
            "fixture audio and 'manual' waits for an operator to post the "
            "bot's reply; neither sends a request anywhere, which is why one "
            "of them is the default."
        ),
    )
    pipeline_fixture_audio_path: str | None = Field(
        default=None,
        description=(
            "Path to a WAV file the 'scripted' adapter replays as the bot's "
            "reply on every turn. **Unset by default, and unset means the "
            "previous behaviour exactly:** a scripted run started through the "
            "API has no replies and fails with 'the scripted bot has no reply "
            "for turn 0'. Setting it is what makes `audio_fixture_test` "
            "complete end to end, which is how the demonstration run works. "
            "The audio is a fixture, not a bot: the scripted adapter reports "
            "`received_from_bot=False`, so the run's "
            "`bot_audio_externally_received` is False and it can never be "
            "mistaken for an external bot test. This is an operator setting "
            "read from the environment; no client value reaches it."
        ),
    )
    pipeline_run_timeout_seconds: float = Field(
        default=600.0,
        gt=0,
        le=7200,
        description=(
            "Wall-clock ceiling on one whole run, on top of the per-turn "
            "timeout. A run that hangs holds a database session, so this bound "
            "exists even though the turn budget also terminates."
        ),
    )
    pipeline_max_concurrent_runs: int = Field(
        default=2,
        ge=1,
        le=50,
        description=(
            "How many runs may execute at once. Bounds provider spend and "
            "memory: each turn decodes audio into Python lists."
        ),
    )
    pipeline_noise_seed: int = Field(
        default=42,
        description=(
            "Default seed for audio degradation. Fixed so a run is "
            "reproducible by default - an artefact nobody can reproduce is not "
            "evidence."
        ),
    )
    pipeline_noise_profile: str = Field(
        default="clean",
        description=(
            "Degradation profile for runs that do not name one. A scenario's "
            "own audio profile takes precedence."
        ),
    )
    pipeline_serve_artefacts: bool = Field(
        default=False,
        description=(
            "Whether a deployed environment may stream stored conversation "
            "audio over the API. Development always may; staging and "
            "production refuse unless this is turned on. There is no "
            "authentication in this application, so on a reachable host the "
            "artefact route would let anyone hear a recorded conversation - "
            "turning it on there is a deliberate act, and the point of the "
            "flag is that nobody does it by accident."
        ),
    )

    @field_validator("caller_provider", mode="before")
    @classmethod
    def _normalise_caller_provider(cls, value: object) -> object:
        """Fold case and whitespace, as for the other provider settings."""
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("pipeline_bot_adapter", "pipeline_noise_profile", mode="before")
    @classmethod
    def _normalise_pipeline_names(cls, value: object) -> object:
        """Fold case and strip whitespace, as the provider settings do."""
        return value.strip().casefold() if isinstance(value, str) else value

    @property
    def caller_audio_root(self) -> Path:
        """The resolved audio storage directory.

        Relative values resolve against the repository root rather than the
        process working directory, so the location does not depend on where
        uvicorn happened to be started from.
        """
        configured = Path(self.caller_audio_storage_dir).expanduser()
        return configured if configured.is_absolute() else (REPO_ROOT / configured)

    @field_validator("speech_provider", mode="before")
    @classmethod
    def _normalise_speech_provider(cls, value: object) -> object:
        """Fold case and whitespace, as for the transcription provider."""
        return value.strip().lower() if isinstance(value, str) else value

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
