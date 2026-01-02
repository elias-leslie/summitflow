"""Health check response models."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ComponentHealth(BaseModel):
    """Health status for a single component."""

    status: str = Field(..., description="Component status: 'healthy', 'degraded', or 'unhealthy'")
    message: str | None = Field(None, description="Additional status information or error message")
    response_time_ms: float | None = Field(None, description="Response time in milliseconds")


class DetailedHealthResponse(BaseModel):
    """Detailed health check response including all system components."""

    status: str = Field(
        ..., description="Overall system status: 'healthy', 'degraded', or 'unhealthy'"
    )
    service: str = Field(..., description="Service name")
    timestamp: datetime = Field(..., description="Health check timestamp (UTC)")
    uptime_seconds: float = Field(..., description="Application uptime in seconds")
    database: ComponentHealth = Field(..., description="Database connection health")
    cache: ComponentHealth = Field(..., description="Redis cache health")
    version: str = Field(..., description="Application version")
