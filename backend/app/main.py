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
from app.core.config import Settings, get_settings
from app.schemas.common import ErrorDetail, ErrorResponse, HealthResponse, ServiceIdentity
from app.services.errors import ConflictError, NotFoundError
from app.services.health import uptime_seconds
from app.services.scenario_loader import (
    ScenarioSyntaxError,
    ScenarioTooLargeError,
    ScenarioValidationError,
)

logger = logging.getLogger("bhashabench")

DESCRIPTION = """
**BhashaBench** is an automated testing and benchmarking platform for
Indian-language voice AI.

Implemented so far:

* **Phase 1** - application skeleton, configuration and health endpoints.
* **Phase 2** - PostgreSQL persistence via Alembic migrations, and the
  scenario engine: YAML authoring, strict validation and CRUD for test suites
  and scenarios.

Telephony, speech services, audio degradation, caller simulation and automated
evaluation are **not** implemented - see `docs/DEVELOPMENT_ROADMAP.md`.
"""


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
