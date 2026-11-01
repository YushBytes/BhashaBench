"""Versioned health endpoints."""

from __future__ import annotations

from fastapi import APIRouter, status

from app.api.deps import SettingsDep
from app.schemas.common import ApiHealthResponse
from app.services.health import build_api_health

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    response_model=ApiHealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Structured API health",
    description=(
        "Reports per-subsystem health for the v1 API, along with process uptime "
        "and the active environment. Subsystems that are not yet probed are "
        "reported as `degraded` with a reason, never as healthy."
    ),
)
async def api_health(settings: SettingsDep) -> ApiHealthResponse:
    """Return a structured health report for the v1 API."""
    return build_api_health(settings)
