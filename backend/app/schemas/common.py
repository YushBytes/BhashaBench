"""Response models shared across the API surface."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

HealthStatus = Literal["ok", "degraded", "unavailable"]


class ServiceIdentity(BaseModel):
    """Identity of the running application, returned by the root endpoint."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "BhashaBench",
                "tagline": "Test your voice AI before India tests it for you.",
                "version": "0.1.0",
                "environment": "development",
                "docs_url": "/docs",
            }
        }
    )

    name: str = Field(description="Human-readable product name.")
    tagline: str = Field(description="Product tagline.")
    version: str = Field(description="Semantic version of this API.")
    environment: str = Field(description="Deployment environment of this process.")
    docs_url: str | None = Field(
        default=None, description="Path to interactive API docs, null when disabled."
    )


class HealthResponse(BaseModel):
    """Minimal liveness payload, suitable for container health checks."""

    model_config = ConfigDict(json_schema_extra={"example": {"status": "ok", "version": "0.1.0"}})

    status: HealthStatus = Field(description="Overall process health.")
    version: str = Field(description="Semantic version of this API.")


class ComponentHealth(BaseModel):
    """Health of a single subsystem the API depends on."""

    name: str = Field(description="Subsystem identifier.")
    status: HealthStatus = Field(description="Health of this subsystem.")
    detail: str = Field(description="Why the subsystem reports this status.")


class ApiHealthResponse(BaseModel):
    """Structured health report for the versioned API."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": "ok",
                "service": "BhashaBench",
                "version": "0.1.0",
                "api_version": "v1",
                "environment": "development",
                "timestamp": "2026-01-01T00:00:00Z",
                "uptime_seconds": 12.5,
                "components": [
                    {
                        "name": "api",
                        "status": "ok",
                        "detail": "FastAPI application is serving requests.",
                    }
                ],
            }
        }
    )

    status: HealthStatus = Field(description="Aggregate status across all components.")
    service: str = Field(description="Product name.")
    version: str = Field(description="Semantic version of this API.")
    api_version: str = Field(description="Version segment of this API surface.")
    environment: str = Field(description="Deployment environment of this process.")
    timestamp: datetime = Field(description="UTC time the report was generated.")
    uptime_seconds: float = Field(ge=0, description="Seconds since application startup.")
    components: list[ComponentHealth] = Field(description="Per-subsystem health.")


class ErrorDetail(BaseModel):
    """Machine-readable description of a failure."""

    type: str = Field(description="Stable, machine-readable error category.")
    message: str = Field(description="Human-readable explanation.")
    status_code: int = Field(description="HTTP status code of the response.")


class ErrorResponse(BaseModel):
    """Uniform error envelope returned for every non-2xx response."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "error": {
                    "type": "not_found",
                    "message": "The requested resource does not exist.",
                    "status_code": 404,
                }
            }
        }
    )

    error: ErrorDetail = Field(description="Details of the failure.")
