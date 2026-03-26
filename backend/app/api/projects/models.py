"""Pydantic models for projects API."""

from datetime import datetime

from pydantic import BaseModel, Field, model_validator


class ProjectPermissionBootstrap(BaseModel):
    """Optional Agent Hub permission bootstrap for a newly registered project."""

    permission_tier: str = "read"
    auto_exec_enabled: bool = False
    execution_start_hour: int = Field(default=0, ge=0, le=23)
    execution_end_hour: int = Field(default=24, ge=1, le=24)
    root_path: str | None = None
    daily_cost_budget_usd: float | None = Field(default=None, ge=0)
    monthly_cost_budget_usd: float | None = Field(default=None, ge=0)
    budget_alert_threshold: float = Field(default=0.8, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_window(self) -> "ProjectPermissionBootstrap":
        """Reject no-op execution windows."""
        if self.execution_start_hour == self.execution_end_hour:
            raise ValueError("execution_start_hour and execution_end_hour cannot be the same")
        return self


class ProjectCreate(BaseModel):
    """Request model for creating a project."""

    id: str
    name: str
    base_url: str
    health_endpoint: str = "/health"
    root_path: str | None = None  # Filesystem path for file scanning
    frontend_port: int | None = None  # Canonical frontend port
    backend_port: int | None = None  # Canonical backend port
    agent_hub_permission: ProjectPermissionBootstrap | None = None


class ProjectResponse(BaseModel):
    """Response model for a project."""

    id: str
    name: str
    base_url: str
    health_endpoint: str
    root_path: str | None = None
    created_at: datetime
    health_status: str | None = None


class ProjectHealthResponse(BaseModel):
    """Response model for project health check."""

    project_id: str
    healthy: bool
    status_code: int | None = None
    response_time_ms: float | None = None
    error: str | None = None
    checked_at: datetime


class ProjectUpdate(BaseModel):
    """Request model for updating a project."""

    name: str | None = None
    base_url: str | None = None
    health_endpoint: str | None = None
    root_path: str | None = None


class ProjectStats(BaseModel):
    """Stats for a single project."""

    features: int = 0
    tasks: int = 0
    bugs: int = 0
    blocked: int = 0


class ProjectWithStats(BaseModel):
    """Project with aggregated stats."""

    id: str
    name: str
    base_url: str
    health_endpoint: str
    root_path: str | None = None
    logo_url: str | None = None
    created_at: datetime
    health_status: str | None = None
    stats: ProjectStats


class ProjectsWithStatsResponse(BaseModel):
    """Response for projects list with stats."""

    projects: list[ProjectWithStats]
    total: int

