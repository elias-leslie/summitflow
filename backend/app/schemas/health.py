"""Health check response models."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ComponentHealth(BaseModel):
    """Health status for a single component."""

    status: str = Field(..., description="Component status: 'healthy', 'degraded', or 'unhealthy'")
    message: str | None = Field(None, description="Additional status information or error message")
    response_time_ms: float | None = Field(None, description="Response time in milliseconds")


class DetailedHealthResponse(BaseModel):
    """Detailed health check response including all system components."""

    model_config = ConfigDict(from_attributes=True)

    status: str = Field(
        ..., description="Overall system status: 'healthy', 'degraded', or 'unhealthy'"
    )
    service: str = Field(..., description="Service name")
    timestamp: datetime = Field(..., description="Health check timestamp (UTC)")
    uptime_seconds: float = Field(..., description="Application uptime in seconds")
    database: ComponentHealth = Field(..., description="Database connection health")
    cache: ComponentHealth = Field(..., description="Redis cache health")
    version: str = Field(..., description="Application version")


class ReadinessResponse(BaseModel):
    """Fresh dependency and schema checks used to admit application traffic."""

    status: str = Field(..., description="Overall readiness: 'ready' or 'not_ready'")
    service: str = Field(..., description="Service name")
    timestamp: datetime = Field(..., description="Readiness check timestamp (UTC)")
    database: ComponentHealth = Field(..., description="Database connection health")
    cache: ComponentHealth = Field(..., description="Redis connectivity health")
    schema_status: ComponentHealth = Field(
        ...,
        alias="schema",
        description="Alembic schema revision health",
    )
    version: str = Field(..., description="Application version")
