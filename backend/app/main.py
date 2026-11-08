"""FastAPI application entry point.

Run locally with:
    uvicorn app.main:app --reload --app-dir backend
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1.router import api_router
from app.caller.errors import (
    CallerConfigurationError,
    CallerError,
    ConversationNotActiveError,
    DuplicateTurnError,
    InvalidCallerDecisionError,
    ScenarioNotUsableError,
    TurnBudgetExhaustedError,
)
from app.core.config import Settings, get_settings
from app.core.languages import UnsupportedLanguageError
from app.pipeline.errors import (
    ArtefactAccessDisabledError,
    AudioValidationError,
    BotAdapterError,
    BotAudioPendingError,
    BotTimeoutError,
    BotUnavailableError,
    DegradationError,
    PipelineConfigurationError,
    PipelineError,
    RunCancelledError,
    RunCapacityExhaustedError,
    RunNotActiveError,
)
from app.schemas.common import ErrorDetail, ErrorResponse, HealthResponse, ServiceIdentity
from app.services.errors import ConflictError, NotFoundError
from app.services.health import uptime_seconds
from app.services.scenario_loader import (
    ScenarioSyntaxError,
    ScenarioTooLargeError,
    ScenarioValidationError,
)
from app.services.transcription_service import classify
from app.speech.errors import (
    InvalidTextError,
    MalformedSpeechResponseError,
    SpeechAuthenticationError,
    SpeechConfigurationError,
    SpeechError,
    SpeechProviderUnavailableError,
    SpeechRateLimitError,
    SpeechTimeoutError,
    UnsupportedAudioConfigError,
    UnsupportedSpeechLanguageError,
    UnsupportedVoiceError,
)
from app.speech.service import classify as classify_speech
from app.transcription.errors import (
    AudioTooLargeError,
    AuthenticationError,
    ConfigurationError,
    InvalidAudioError,
    MalformedProviderResponseError,
    ProviderUnavailableError,
    RateLimitError,
    StreamClosedError,
    TranscriptionCancelledError,
    TranscriptionError,
    TranscriptionTimeoutError,
    UnsupportedFormatError,
)
from app.transcription.errors import (
    UnsupportedLanguageError as ProviderUnsupportedLanguageError,
)
from app.transcription.redaction import redact

logger = logging.getLogger("bhashabench")

DESCRIPTION = """
**BhashaBench** is an automated testing and benchmarking platform for
Indian-language voice AI.

Implemented so far:

* **Phase 1** - application skeleton, configuration and health endpoints.
* **Phase 2** - PostgreSQL persistence via Alembic migrations, and the
  scenario engine: YAML authoring, strict validation and CRUD for test suites
  and scenarios.
* **Phase 3** - the scenario library: cross-suite search, suite editing, copy
  and move, a 13-language catalogue, YAML bundles and the `bhashabench` CLI.
* **Phase 4** - speech to text behind a provider-independent interface, with a
  Gnani Prisma adapter and an offline fake. Nothing is persisted.
* **Phase 5** - text to speech behind a `SynthesisProvider` interface, with a
  Gnani Timbre adapter and an offline fake. Returns binary audio; nothing is
  persisted.
* **Phase 6** - a simulated caller that conducts scenario-driven multi-turn
  conversations, persisted as call sessions and turns. The caller is a
  **deterministic rule engine**; Gnani Evon is *not* integrated - see
  `docs/PROVIDERS.md`.

Telephony, audio degradation and automated evaluation are **not** implemented -
see `docs/DEVELOPMENT_ROADMAP.md`.
"""


_TRANSCRIPTION_STATUS: dict[type[TranscriptionError], int] = {
    # A credential problem is ours, not the caller's: BhashaBench's own API is
    # unauthenticated in this phase, so returning 401 would tell a client to
    # fix credentials they do not have. 502 says "the upstream rejected us",
    # which is what actually happened.
    AuthenticationError: status.HTTP_502_BAD_GATEWAY,
    ConfigurationError: status.HTTP_500_INTERNAL_SERVER_ERROR,
    # Caller-fixable input problems.
    InvalidAudioError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    ProviderUnsupportedLanguageError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    UnsupportedFormatError: status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
    AudioTooLargeError: status.HTTP_413_CONTENT_TOO_LARGE,
    # Upstream conditions, passed through with the status that describes our
    # relationship to the provider rather than the provider's own code.
    RateLimitError: status.HTTP_429_TOO_MANY_REQUESTS,
    ProviderUnavailableError: status.HTTP_502_BAD_GATEWAY,
    MalformedProviderResponseError: status.HTTP_502_BAD_GATEWAY,
    StreamClosedError: status.HTTP_502_BAD_GATEWAY,
    TranscriptionTimeoutError: status.HTTP_504_GATEWAY_TIMEOUT,
    # 499 is not in the RFCs - it is nginx's de-facto "client closed request",
    # and the closest honest answer when the caller abandoned the work.
    TranscriptionCancelledError: 499,
}
"""Transcription error type -> HTTP status.

Exact types, not `isinstance` walks: `AuthenticationError` and
`RateLimitError` are siblings, and a subclass added later should have to
choose its status deliberately rather than inherit a surprising one. Anything
absent falls back to 502, which is the honest default for "the provider leg of
this request failed".
"""


_SPEECH_STATUS: dict[type[SpeechError], int] = {
    # Same reasoning as the transcription map: a provider credential problem is
    # ours, not the caller's, so it is a 502 rather than a 401 the caller
    # cannot act on. 402 and 403 arrive as the same class and get the same
    # treatment - and a 403 here is worth noticing, because a key that works
    # for Prisma need not carry the Timbre scope.
    SpeechAuthenticationError: status.HTTP_502_BAD_GATEWAY,
    SpeechConfigurationError: status.HTTP_500_INTERNAL_SERVER_ERROR,
    # Caller-fixable input problems.
    InvalidTextError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    UnsupportedVoiceError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    UnsupportedSpeechLanguageError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    UnsupportedAudioConfigError: status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
    # Upstream conditions.
    SpeechRateLimitError: status.HTTP_429_TOO_MANY_REQUESTS,
    SpeechProviderUnavailableError: status.HTTP_502_BAD_GATEWAY,
    MalformedSpeechResponseError: status.HTTP_502_BAD_GATEWAY,
    SpeechTimeoutError: status.HTTP_504_GATEWAY_TIMEOUT,
}
"""Speech error type -> HTTP status. Exact types, defaulting to 502."""


_PIPELINE_STATUS: dict[type[PipelineError], int] = {
    # Temporary and about the server's capacity, not the request: the run was
    # not started and keeps its state, so retrying later is the right move.
    RunCapacityExhaustedError: status.HTTP_503_SERVICE_UNAVAILABLE,
    # A configuration the engine cannot honour is the request's fault: an
    # unimplemented mode, an unknown adapter, a run that is not waiting for
    # audio. 422, not 500.
    PipelineConfigurationError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    # The recording exists; this environment will not stream it. Refusing a
    # request the server understands and declines is 403, not 404 - saying
    # "no such artefact" would be a lie about what is on disk.
    ArtefactAccessDisabledError: status.HTTP_403_FORBIDDEN,
    # The run has already finished. The client asked too late.
    RunNotActiveError: status.HTTP_409_CONFLICT,
    RunCancelledError: status.HTTP_409_CONFLICT,
    # Audio that did not survive inspection, and a degradation step that could
    # not run. Both are about the payload rather than the server.
    AudioValidationError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    DegradationError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    # Waiting for an operator is not an error condition; 409 says "not now"
    # rather than 502, which would blame a bot that was never contacted.
    BotAudioPendingError: status.HTTP_409_CONFLICT,
    BotTimeoutError: status.HTTP_504_GATEWAY_TIMEOUT,
    BotUnavailableError: status.HTTP_502_BAD_GATEWAY,
    BotAdapterError: status.HTTP_502_BAD_GATEWAY,
}

_CALLER_STATUS: dict[type[CallerError], int] = {
    CallerConfigurationError: status.HTTP_500_INTERNAL_SERVER_ERROR,
    # A finished conversation asked for another turn, or two requests racing to
    # create the same turn index. Both are conflicts with existing state, not
    # bad requests - the request would have been fine a moment earlier.
    ConversationNotActiveError: status.HTTP_409_CONFLICT,
    DuplicateTurnError: status.HTTP_409_CONFLICT,
    # A provider returned something unusable. 422 rather than 500: for the rule
    # engine it means a rule is wrong, but for a future model provider it is
    # the ordinary case of a model not following its output contract, and the
    # caller of the API can legitimately retry with a different scenario.
    InvalidCallerDecisionError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    ScenarioNotUsableError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    TurnBudgetExhaustedError: status.HTTP_409_CONFLICT,
}
"""Caller error type -> HTTP status. Exact types, defaulting to 422."""


def _error_response(status_code: int, error_type: str, message: str) -> JSONResponse:
    """Build a JSON response using the uniform error envelope."""
    payload = ErrorResponse(
        error=ErrorDetail(type=error_type, message=message, status_code=status_code)
    )
    return JSONResponse(status_code=status_code, content=payload.model_dump())


def register_exception_handlers(app: FastAPI) -> None:
    """Install handlers so every error shares one response shape.

    Without this, FastAPI emits `{"detail": ...}` for HTTP errors and a bare
    list for validation errors, which clients would have to special-case.
    """

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        error_type = "not_found" if exc.status_code == status.HTTP_404_NOT_FOUND else "http_error"
        return _error_response(exc.status_code, error_type, str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return _error_response(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "validation_error",
            f"Request validation failed: {exc.errors()}",
        )

    # -- Phase 2 domain errors ------------------------------------------------
    # Services raise these rather than HTTPException, so the service layer
    # stays usable outside a request and the HTTP mapping lives only here.

    @app.exception_handler(NotFoundError)
    async def handle_not_found(_request: Request, exc: NotFoundError) -> JSONResponse:
        return _error_response(status.HTTP_404_NOT_FOUND, "not_found", str(exc))

    @app.exception_handler(ConflictError)
    async def handle_conflict(_request: Request, exc: ConflictError) -> JSONResponse:
        return _error_response(status.HTTP_409_CONFLICT, "conflict", str(exc))

    @app.exception_handler(UnsupportedLanguageError)
    async def handle_unsupported_language(
        _request: Request, exc: UnsupportedLanguageError
    ) -> JSONResponse:
        """An unsupported language tag is invalid input, not a server fault.

        Inside a scenario document this already surfaces as a Pydantic
        validation error. This handler covers the other path: a bad
        `?language=` filter on the search endpoint, where the catalogue is
        consulted directly. Without it the error is a `ValueError`, which the
        catch-all handler would turn into an opaque 500.
        """
        return _error_response(status.HTTP_422_UNPROCESSABLE_CONTENT, "validation_error", str(exc))

    @app.exception_handler(ScenarioTooLargeError)
    async def handle_scenario_too_large(
        _request: Request, exc: ScenarioTooLargeError
    ) -> JSONResponse:
        return _error_response(status.HTTP_413_CONTENT_TOO_LARGE, "payload_too_large", str(exc))

    @app.exception_handler(ScenarioSyntaxError)
    async def handle_scenario_syntax(_request: Request, exc: ScenarioSyntaxError) -> JSONResponse:
        return _error_response(status.HTTP_422_UNPROCESSABLE_CONTENT, "yaml_syntax_error", str(exc))

    @app.exception_handler(ScenarioValidationError)
    async def handle_scenario_validation(
        _request: Request, exc: ScenarioValidationError
    ) -> JSONResponse:
        return _error_response(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "scenario_validation_error", str(exc)
        )

    # -- Phase 4 transcription errors -----------------------------------------
    # One handler for the whole family, mapping by type rather than by a
    # status code the adapter chose. A provider's 401 and a provider's
    # unreachable socket are both failures of ours to report honestly, and
    # neither should surface as the provider's own status code: a client
    # calling BhashaBench must not have to guess whether a 401 means *their*
    # credentials or ours.

    @app.exception_handler(TranscriptionError)
    async def handle_transcription_error(
        _request: Request, exc: TranscriptionError
    ) -> JSONResponse:
        status_code = _TRANSCRIPTION_STATUS.get(type(exc), status.HTTP_502_BAD_GATEWAY)
        if isinstance(exc, ConfigurationError):
            # A misconfigured server, not a bad request. Logged because
            # somebody has to fix the deployment.
            logger.error(
                "Transcription provider is misconfigured: %s",
                exc,
                extra={"provider": exc.provider},
            )
        # Redacted here, at the outermost boundary, as well as inside the
        # adapters. The adapters are the first line of defence; this is the one
        # that still holds when a future provider's adapter forgets, because
        # every transcription error leaves the process through this function.
        return _error_response(status_code, classify(exc), redact(exc))

    # -- Phase 5 speech-synthesis errors --------------------------------------

    @app.exception_handler(SpeechError)
    async def handle_speech_error(_request: Request, exc: SpeechError) -> JSONResponse:
        status_code = _SPEECH_STATUS.get(type(exc), status.HTTP_502_BAD_GATEWAY)
        if isinstance(exc, SpeechConfigurationError):
            logger.error(
                "Speech provider is misconfigured: %s", exc, extra={"provider": exc.provider}
            )
        # Redacted at the boundary as well as in the adapter, for the reason
        # given on the transcription handler.
        return _error_response(status_code, classify_speech(exc), redact(exc))

    # -- Phase 6 caller errors ------------------------------------------------

    @app.exception_handler(CallerError)
    async def handle_caller_error(_request: Request, exc: CallerError) -> JSONResponse:
        status_code = _CALLER_STATUS.get(type(exc), status.HTTP_422_UNPROCESSABLE_CONTENT)
        if isinstance(exc, CallerConfigurationError):
            logger.error("Caller provider is misconfigured: %s", exc)
        name = type(exc).__name__
        if name.endswith("Error"):
            name = name[: -len("Error")]
        snake = "".join(f"_{c.lower()}" if c.isupper() else c for c in name).lstrip("_")
        return _error_response(status_code, f"{snake}_error", redact(exc))

    # -- Phase 7 pipeline errors ----------------------------------------------

    @app.exception_handler(PipelineError)
    async def handle_pipeline_error(_request: Request, exc: PipelineError) -> JSONResponse:
        status_code = _PIPELINE_STATUS.get(type(exc), status.HTTP_422_UNPROCESSABLE_CONTENT)
        if isinstance(exc, PipelineConfigurationError):
            logger.error("Pipeline is misconfigured: %s", exc)
        name = type(exc).__name__
        if name.endswith("Error"):
            name = name[: -len("Error")]
        snake = "".join(f"_{c.lower()}" if c.isupper() else c for c in name).lstrip("_")
        # Redacted: a pipeline error can carry a provider's message, and those
        # have carried an Authorization header before now.
        return _error_response(status_code, f"{snake}_error", redact(exc))

    @app.exception_handler(Exception)
    async def handle_unexpected_error(_request: Request, exc: Exception) -> JSONResponse:
        # Log the detail server-side; never return internals to the client.
        logger.exception("Unhandled exception while serving request", exc_info=exc)
        return _error_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "internal_error",
            "An unexpected internal error occurred.",
        )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Log configuration at startup, warm the settings cache, and tear down.

    Resolving settings here means a misconfigured deployment fails at boot
    rather than on the first request.
    """
    settings = get_settings()
    logging.basicConfig(
        level=logging.INFO if settings.is_production else logging.DEBUG,
        format="%(asctime)s %(levelname)-8s %(name)s %(message)s",
    )
    logger.info(
        "Starting %s v%s in %s mode",
        settings.app_name,
        settings.app_version,
        settings.app_env,
    )
    yield
    logger.info("Shutting down %s after %.1fs", settings.app_name, uptime_seconds())


def create_app(settings: Settings | None = None) -> FastAPI:
    """Construct the FastAPI application.

    Exposed as a factory so tests can build an app against custom settings
    without mutating global state.
    """
    settings = settings or get_settings()

    app = FastAPI(
        title=settings.app_name,
        summary=settings.app_tagline,
        description=DESCRIPTION,
        version=settings.app_version,
        docs_url=settings.docs_url,
        redoc_url=settings.redoc_url,
        openapi_url=settings.openapi_url,
        lifespan=lifespan,
        contact={"name": "BhashaBench", "url": "https://github.com/YushBytes/BhashaBench"},
        license_info={"name": "MIT"},
        responses={
            status.HTTP_404_NOT_FOUND: {"model": ErrorResponse, "description": "Not found"},
            status.HTTP_500_INTERNAL_SERVER_ERROR: {
                "model": ErrorResponse,
                "description": "Internal server error",
            },
        },
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)

    @app.get(
        "/",
        response_model=ServiceIdentity,
        tags=["meta"],
        summary="Service identity",
        description="Returns the product name, tagline, version and environment.",
    )
    async def root() -> ServiceIdentity:
        """Identify the running service."""
        return ServiceIdentity(
            name=settings.app_name,
            tagline=settings.app_tagline,
            version=settings.app_version,
            environment=str(settings.app_env),
            docs_url=settings.docs_url,
        )

    @app.get(
        "/health",
        response_model=HealthResponse,
        tags=["health"],
        summary="Liveness probe",
        description=(
            "Minimal liveness check for load balancers and container health "
            "checks. For per-subsystem detail use the versioned endpoint."
        ),
    )
    async def health() -> HealthResponse:
        """Report that the process is alive."""
        return HealthResponse(status="ok", version=settings.app_version)

    app.include_router(api_router, prefix=settings.api_v1_prefix)

    return app


app = create_app()
