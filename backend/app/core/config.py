"""Application configuration.

Settings are resolved from, in order of increasing precedence: the field
defaults below, a `.env` file at the repository root, and real process
environment variables. This lets Docker Compose and CI override anything
without a file on disk.

Only settings that something actually reads are modelled here. A setting that
nothing consumes is dead code, so a variable stays in `.env.example` - where it
documents the configuration surface - until the phase that uses it arrives.
Phase 4 promoted the Gnani speech-to-text settings to real fields and Phase 5
the text-to-speech ones; Twilio (Phase 8) and the run-safety limits are still
declared only in `.env.example`.
"""

from __future__ import annotations

import os
from decimal import Decimal
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# `backend/app/core/config.py` -> repository root is four levels up.

if TYPE_CHECKING:
    from app.storage.base import BlobStore

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

# And from `app.caller.llm.clients.sarvam_contract`, asserted equal the same way.
SARVAM_DEFAULT_BASE_URL = "https://api.sarvam.ai"


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

    # -- Authentication (Phase 14) -------------------------------------------
    auth_password_hash_log2_n: int = Field(
        default=17,
        ge=10,
        le=20,
        description=(
            "scrypt cost as log2 N. 17 is OWASP's minimum and is enforced in "
            "staging and production; tests lower it to stay fast."
        ),
    )
    auth_session_ttl_hours: float = Field(
        default=12.0,
        gt=0,
        le=720,
        description="Absolute session lifetime. Activity never extends it.",
    )
    auth_session_idle_minutes: float = Field(
        default=60.0,
        gt=0,
        le=10080,
        description="A session unused for this long is refused.",
    )
    auth_max_failed_logins: int = Field(
        default=10,
        ge=1,
        le=1000,
        description="Consecutive failed logins before the account is locked.",
    )
    auth_lockout_minutes: float = Field(
        default=15.0,
        gt=0,
        le=1440,
        description="How long a locked account refuses every login, right or wrong.",
    )
    auth_allow_signup: bool = Field(
        default=False,
        description=(
            "Whether POST /auth/signup is open. Off by default: the first user "
            "is created with `bhashabench users create`, and owners invite the rest."
        ),
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
    gnani_api_key: SecretStr = Field(
        default=SecretStr(""),
        description=(
            "Gnani platform API key, sent as the X-API-Key-ID header. Empty by "
            "default: an unset credential must fail loudly at provider "
            "construction, not resolve to something that looks like a key. A "
            "`SecretStr`, so it does not appear in a repr, a dump or a failing "
            "test's assertion diff."
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
    # The default provider is a rule engine and needs no credential. Gnani Evon
    # is not integrated - see docs/PROVIDERS.md - so there is deliberately no
    # EVON_API_KEY here to suggest otherwise.
    caller_provider: str = Field(
        default="deterministic",
        description=(
            "Which caller strategy to use. 'deterministic' is a rule engine, not "
            "a language model, and is the default. 'sarvam' asks a Sarvam model "
            "for each turn and falls back to the rule engine; while live calls "
            "are unauthorised every turn is a recorded fallback."
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

    # -- Language-model caller (Phase 6) -------------------------------------
    # Nothing here can cause a billable request on its own. Live calls also
    # need `LIVE_CALLS_AUTHORISED` in `app/caller/llm/budget.py`, which is a
    # constant, not a setting, and is False.
    sarvam_api_key: SecretStr = Field(
        default=SecretStr(""),
        description=(
            "Sarvam API key, sent as the `api-subscription-key` header. Empty by "
            "default. A `SecretStr`, so it does not appear in a repr or a dump."
        ),
    )
    sarvam_api_base_url: str = Field(
        default=SARVAM_DEFAULT_BASE_URL,
        description="Sarvam REST base URL. Must be https: the request carries the key.",
    )
    caller_llm_model: str = Field(
        default="",
        description=(
            "Exact model identifier for CALLER_PROVIDER=sarvam: 'sarvam-105b' or "
            "'sarvam-105b-conversations'. No default - the model a benchmark ran "
            "on is chosen, never assumed."
        ),
    )
    caller_llm_live_calls_enabled: bool = Field(
        default=False,
        description=(
            "Operator switch for live language-model calls. Necessary and not "
            "sufficient: the code-level authorisation must also be granted."
        ),
    )
    caller_llm_live_budget_inr: Decimal = Field(
        default=Decimal(0),
        ge=0,
        le=100,
        description=(
            "Total rupees live language-model calls may commit, across every run "
            "and restart. Zero by default, so nothing can be spent until a figure "
            "is chosen. The hard maximum is 100 and cannot be raised here."
        ),
    )
    caller_llm_budget_ledger_path: str = Field(
        default="storage/llm-budget/ledger.json",
        description=(
            "Where the live budget ledger is kept, relative to the repository "
            "root unless absolute. `storage/` is git-ignored."
        ),
    )
    caller_llm_max_cost_per_run_inr: Decimal = Field(
        default=Decimal(5),
        gt=0,
        le=100,
        description="Most one conversation may commit, worst case, in rupees.",
    )
    caller_llm_cost_margin: Decimal = Field(
        default=Decimal("0.18"),
        ge=0,
        le=1,
        description=(
            "Fraction added to the vendor's published token prices, which exclude "
            "GST. 0.18 is this project's allowance for that tax, not a vendor "
            "figure. Lowering it makes estimates less safe."
        ),
    )
    caller_llm_max_output_tokens: int = Field(
        default=300,
        ge=16,
        le=4096,
        description=(
            "Most tokens one generated turn may produce. 4096 is the lowest "
            "documented per-plan cap. Reasoning tokens, when enabled, count "
            "toward this."
        ),
    )
    caller_llm_max_prompt_tokens: int = Field(
        default=8000,
        ge=256,
        le=120_000,
        description=(
            "Most tokens one prompt may hold, compared with an upper bound "
            "(UTF-8 bytes), not a tokenizer's count. Over it, the turn falls back."
        ),
    )
    caller_llm_max_attempts: int = Field(
        default=2,
        ge=1,
        le=3,
        description="Total requests allowed for one turn, counting every kind of failure.",
    )
    caller_llm_request_timeout_seconds: float = Field(
        default=30.0,
        gt=0,
        le=120,
        description="Ceiling on one language-model request.",
    )
    caller_llm_temperature: float = Field(
        default=0.5,
        ge=0,
        le=2,
        description=(
            "Sampling temperature, always sent explicitly because the vendor's "
            "documented default is contradictory."
        ),
    )
    caller_llm_seed: int | None = Field(
        default=None,
        ge=0,
        description=(
            "Seed sent with each request, if set. Best-effort by the vendor's own "
            "description; recorded as sent, never as honoured."
        ),
    )
    caller_llm_reasoning_effort: str = Field(
        default="",
        description=(
            "Reasoning effort for 'sarvam-105b': low, medium, high or max. Empty "
            "disables reasoning, which is the default: reasoning is billed as "
            "output and spends the output limit. Must be empty for "
            "'sarvam-105b-conversations'."
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
    pipeline_fixture_bot_text_path: str | None = Field(
        default=None,
        description=(
            "Path to a UTF-8 text file of bot replies, one per line, that the "
            "'scripted' adapter uses in `offline_simulation`. Lines are used in "
            "order and repeated from the top when exhausted, so a run always "
            "ends on its turn budget; blank lines and lines starting with '#' "
            "are ignored. **Unset, an offline scripted run fails on its first "
            "bot turn with an error naming this setting** rather than stalling "
            "in `running`. The replies are a fixture, not a bot. This is an "
            "operator setting read from the environment; no client value "
            "reaches it."
        ),
    )
    # -- HTTP text bot (early Phase 9) ---------------------------------------
    # Everything the `http` adapter needs. Nothing is reachable until
    # BOT_HTTP_ALLOWED_HOSTS names the bot's host: the allowlist is empty by
    # default, so an unconfigured deployment can contact no bot at all.
    bot_ws_url: str = Field(
        default="",
        description=(
            "The ws:// or wss:// URL of a bot speaking bhashabench-voice-bot/1, for the "
            "`ws_voice` adapter. Authenticated with BOT_HTTP_TOKEN and checked against "
            "BOT_HTTP_ALLOWED_HOSTS like the text adapter."
        ),
    )
    bot_http_base_url: str = Field(
        default="",
        description=(
            "Base URL of a bot speaking bhashabench-text-bot/1, e.g. "
            "'https://bot.example.com'. Checked against the allowlist and the "
            "outbound address rules before every request."
        ),
    )
    bot_http_token: SecretStr = Field(
        default=SecretStr(""),
        description="Bearer token sent to the bot. A `SecretStr`; never logged.",
    )
    bot_http_allowed_hosts: str = Field(
        default="",
        description=(
            "Comma-separated hosts the adapter may contact, exactly or as "
            "'*.example.com'. Empty refuses every host."
        ),
    )
    bot_http_allow_loopback: bool = Field(
        default=False,
        description=(
            "Permit a loopback bot (the local reference bot). Development and "
            "tests only: refused when APP_ENV is staging or production."
        ),
    )
    bot_http_allow_private: bool = Field(
        default=False,
        description="Permit a bot on a private network range (RFC 1918, ULA).",
    )
    bot_http_timeout_seconds: float = Field(
        default=10.0,
        gt=0,
        le=120,
        description="Ceiling on one whole request to the bot, in seconds.",
    )
    bot_http_max_attempts: int = Field(
        default=2,
        ge=1,
        le=5,
        description=(
            "Requests per turn, counting retries. Only a connection that never "
            "opened or a 502/503/504 is retried, with the same idempotency key."
        ),
    )

    pipeline_recovery_interval_seconds: float = Field(
        default=300.0,
        ge=0,
        le=86400,
        description=(
            "How often the server closes runs left in flight with nothing executing "
            "them (a crash, a restart). 0 disables it; `bhashabench runs recover-stale` "
            "still works by hand. A run counts as stale only after "
            "PIPELINE_RUN_TIMEOUT_SECONDS of inactivity plus a minute."
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
    # -- HTTP hardening (Phase 14, part 2) -------------------------------------
    rate_limit_requests_per_minute: int = Field(
        default=600,
        ge=0,
        le=100_000,
        description="Per client address, across /api/. 0 disables. Per process.",
    )
    rate_limit_logins_per_minute: int = Field(
        default=10,
        ge=0,
        le=10_000,
        description="Login attempts per client address and, separately, per email. 0 disables.",
    )
    trust_forwarded_for: bool = Field(
        default=False,
        description=(
            "Key limits by the left-most X-Forwarded-For entry. Only behind a proxy that "
            "overwrites the header; otherwise a client chooses its own key."
        ),
    )

    # -- Telephony (Phase 8): a mocked provider only ---------------------------
    telephony_provider: str = Field(
        default="",
        description=(
            "Empty (telephony off) or `mock`. No vendor adapter exists; any other "
            "value is refused when a call is attempted, with the reason."
        ),
    )
    telephony_webhook_secret: SecretStr = Field(
        default=SecretStr(""),
        description="Signs provider events. Fewer than 32 characters verifies nothing.",
    )
    telephony_allowed_numbers: str = Field(
        default="",
        description="Comma-separated E.164 bot numbers. Empty allows no call at all.",
    )
    telephony_max_calls_per_run: int = Field(default=3, ge=1, le=100)
    telephony_max_concurrent_calls: int = Field(default=1, ge=1, le=100)
    telephony_max_minutes_per_day: float = Field(default=30.0, gt=0, le=1440)

    retention_days: int | None = Field(
        default=None,
        ge=1,
        le=36500,
        description=(
            "Delete finished runs, their evidence and their audio this many days "
            "after they finished, when `bhashabench runs purge --apply` runs. "
            "Unset keeps everything: no deletion happens without both this and "
            "an explicit --apply."
        ),
    )
    storage_backend: str = Field(
        default="local",
        description=(
            "Where artefacts are kept. Only `local` exists: files under "
            "CALLER_AUDIO_STORAGE_DIR. No cloud adapter is implemented, and an "
            "unknown value fails at startup rather than silently writing locally."
        ),
    )

    @field_validator("caller_provider", mode="before")
    @classmethod
    def _normalise_caller_provider(cls, value: object) -> object:
        """Fold case and whitespace, as for the other provider settings."""
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("caller_llm_model", "caller_llm_reasoning_effort", mode="before")
    @classmethod
    def _normalise_llm_names(cls, value: object) -> object:
        """Fold case and whitespace. Membership is the registry's to check."""
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("caller_llm_seed", mode="before")
    @classmethod
    def _blank_seed_is_no_seed(cls, value: object) -> object:
        """`CALLER_LLM_SEED=` in a copied `.env.example` means unset, not an error."""
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("sarvam_api_base_url", mode="before")
    @classmethod
    def _require_https_for_sarvam(cls, value: object) -> object:
        """Reject a Sarvam base URL that would send the key in the clear."""
        if isinstance(value, str) and value.strip():
            url = value.strip().rstrip("/")
            if not url.startswith("https://"):
                raise ValueError(f"SARVAM_API_BASE_URL must start with https://, got '{url}'")
            return url
        return value

    @property
    def caller_llm_budget_ledger(self) -> Path:
        """The resolved ledger path; relative values resolve against the repository root."""
        configured = Path(self.caller_llm_budget_ledger_path).expanduser()
        return configured if configured.is_absolute() else (REPO_ROOT / configured)

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
    def _reject_loopback_bots_when_deployed(self) -> Settings:
        """A deployed server reaching its own loopback is an SSRF primitive."""
        if self.app_env in (AppEnv.PRODUCTION, AppEnv.STAGING) and self.bot_http_allow_loopback:
            raise ValueError(
                f"BOT_HTTP_ALLOW_LOOPBACK is enabled while APP_ENV={self.app_env}. "
                "Loopback bots are for development; a deployed server must not "
                "send requests to its own host."
            )
        return self

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

    @field_validator("telephony_allowed_numbers")
    @classmethod
    def _valid_allowlist(cls, value: str) -> str:
        from app.telephony.guardrails import parse_allowlist

        parse_allowlist(value)  # one malformed entry fails startup
        return value

    @field_validator("telephony_provider", mode="before")
    @classmethod
    def _normalise_telephony_provider(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("retention_days", mode="before")
    @classmethod
    def _blank_retention_is_unset(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("storage_backend", mode="before")
    @classmethod
    def _known_storage_backend(cls, value: object) -> object:
        from app.storage.registry import SUPPORTED_BACKENDS, build_blob_store

        name = value.strip().lower() if isinstance(value, str) else value
        if name not in SUPPORTED_BACKENDS:
            try:
                build_blob_store(str(name), ".")
            except Exception as exc:  # the registry's own explanation
                raise ValueError(str(exc)) from exc
        return name

    def artefact_store_blobs(self) -> BlobStore:
        """The configured blob store for artefacts."""
        from app.storage.registry import build_blob_store

        return build_blob_store(self.storage_backend, self.caller_audio_root)

    @model_validator(mode="after")
    def _require_full_password_cost_when_deployed(self) -> Settings:
        """A lowered scrypt cost is for tests; a deployment must not inherit it."""
        deployed = (AppEnv.PRODUCTION, AppEnv.STAGING)
        if self.app_env in deployed and self.auth_password_hash_log2_n < 17:
            raise ValueError(
                f"AUTH_PASSWORD_HASH_LOG2_N={self.auth_password_hash_log2_n} is below 17 "
                f"while APP_ENV={self.app_env}; 17 is the minimum for a deployment."
            )
        return self

    @property
    def auth_cookie_secure(self) -> bool:
        """`Secure` on the session cookie everywhere but a local http:// setup."""
        return self.app_env not in (AppEnv.DEVELOPMENT, AppEnv.TEST)

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
