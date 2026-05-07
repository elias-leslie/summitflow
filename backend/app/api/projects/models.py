"""Pydantic models for projects API."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

type ProjectCategory = Literal["production", "testing", "dev"]


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

    @field_validator("permission_tier", mode="before")
    @classmethod
    def normalize_permission_tier(cls, value: object) -> str:
        tier = str(value or "read").strip().lower()
        if tier in {"write", "yolo"}:
            return "full"
        if tier in {"off", "read", "full"}:
            return tier
        raise ValueError("permission_tier must be one of: off, read, full")

    @model_validator(mode="after")
    def validate_window(self) -> "ProjectPermissionBootstrap":
        """Reject no-op execution windows."""
        if self.execution_start_hour == self.execution_end_hour:
            raise ValueError("execution_start_hour and execution_end_hour cannot be the same")
        return self


class ProjectOnboardingRequest(BaseModel):
    """Standard SummitFlow onboarding settings for a project."""

    enable_backup_schedule: bool = True
    backup_frequency: Literal["daily", "weekly", "monthly", "hourly"] = "daily"
    backup_retention_days: int = Field(default=30, ge=1)
    queue_initial_backup: bool = True


class ProjectOnboardingResponse(BaseModel):
    """Queued onboarding response."""

    status: str
    project_id: str
    backup_schedule_enabled: bool
    backup_frequency: str
    backup_retention_days: int
    queue_initial_backup: bool


class ProjectCreate(BaseModel):
    """Request model for creating a project."""

    id: str
    name: str
    base_url: str | None = None
    public_url: str | None = None
    health_endpoint: str = "/health"
    root_path: str | None = None  # Filesystem path for file scanning
    frontend_port: int | None = None  # Canonical frontend port
    backend_port: int | None = None  # Canonical backend port
    category: ProjectCategory = "dev"
    summitflow_hosted: bool = False
    agent_hub_permission: ProjectPermissionBootstrap | None = None
    onboarding: ProjectOnboardingRequest | None = None


class ProjectResponse(BaseModel):
    """Response model for a project."""

    id: str
    name: str
    base_url: str
    public_url: str
    health_endpoint: str
    root_path: str | None = None
    category: ProjectCategory
    sidebar_rank: int | None = Field(default=None, ge=0)
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
    public_url: str | None = None
    health_endpoint: str | None = None
    root_path: str | None = None
    category: ProjectCategory | None = None
    sidebar_rank: int | None = Field(default=None, ge=0)


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
    public_url: str
    health_endpoint: str
    root_path: str | None = None
    logo_url: str | None = None
    category: ProjectCategory
    sidebar_rank: int | None = Field(default=None, ge=0)
    created_at: datetime
    health_status: str | None = None
    stats: ProjectStats


class ProjectsWithStatsResponse(BaseModel):
    """Response for projects list with stats."""

    projects: list[ProjectWithStats]
    total: int
