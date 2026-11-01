"""Health reporting.

Lives in the service layer rather than the route handler so that the health
report can be assembled and tested without an HTTP client, and so later
phases can add real dependency probes (database, Gnani, Twilio) in one place.
"""

from __future__ import annotations

from app.core.config import Settings, describe_environment
from app.schemas.common import ApiHealthResponse, ComponentHealth, HealthStatus
from app.utils.timing import monotonic_seconds, utc_now

# Captured at import time, which is close enough to process start for an
# uptime figure and avoids needing global mutable state.
_STARTED_AT_MONOTONIC: float = monotonic_seconds()


def uptime_seconds() -> float:
    """Return seconds elapsed since the application module was loaded."""
    return monotonic_seconds() - _STARTED_AT_MONOTONIC


def _aggregate(components: list[ComponentHealth]) -> HealthStatus:
    """Collapse per-component statuses into a single overall status."""
    statuses = {component.status for component in components}
    if "unavailable" in statuses:
        return "unavailable"
    if "degraded" in statuses:
        return "degraded"
    return "ok"


def collect_components(settings: Settings) -> list[ComponentHealth]:
    """Describe each subsystem the API currently depends on.

    Phase 1 reports only what it can genuinely verify: that the application is
    serving requests, and whether configuration was loaded. The database is
    reported as `degraded` with an explicit reason because no connection is
    attempted yet - it is not claimed to be healthy.
    """
    sources = describe_environment()

    return [
        ComponentHealth(
            name="api",
            status="ok",
            detail="FastAPI application is serving requests.",
        ),
        ComponentHealth(
            name="configuration",
            status="ok",
            detail=(
                f"Settings loaded for environment '{settings.app_env}'; "
                f".env file {sources['env_file']}, DATABASE_URL {sources['database_url']}."
            ),
        ),
        ComponentHealth(
            name="database",
            status="degraded",
            detail=(
                "Not probed. A connection URL is configured but the persistence "
                "layer is not implemented in this phase."
            ),
        ),
    ]


def build_api_health(settings: Settings) -> ApiHealthResponse:
    """Assemble the structured health report for the versioned API."""
    components = collect_components(settings)

    return ApiHealthResponse(
        status=_aggregate(components),
        service=settings.app_name,
        version=settings.app_version,
        api_version="v1",
        environment=str(settings.app_env),
        timestamp=utc_now(),
        uptime_seconds=round(uptime_seconds(), 3),
        components=components,
    )
