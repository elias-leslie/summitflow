"""Pydantic models for projects API."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from ...project_identity import ProjectLifecycle
from ..checkpoint_models import CheckpointResponse

type ProjectCategory = Literal["production", "testing", "dev"]


class ProjectPermissionBootstrap(BaseModel):
    """Optional Agent Hub permission bootstrap for a newly registered project."""

    root_path: str | None = None
    daily_cost_budget_usd: float | None = Field(default=None, ge=0)
    monthly_cost_budget_usd: float | None = Field(default=None, ge=0)
    budget_alert_threshold: float = Field(default=0.8, ge=0.0, le=1.0)


class ProjectOnboardingRequest(BaseModel):
    """Standard SummitFlow onboarding for a project: write its `.index.yaml`. Backups cover every project on their own."""


class ProjectOnboardingResponse(BaseModel):
    """Queued onboarding response."""

    status: str
    project_id: str


class ProjectCreate(BaseModel):
    """Request model for creating a project."""

    id: str
    name: str
    base_url: str | None = None
    public_url: str | None = None
    health_endpoint: str = "/health"
    root_path: str | None = None  # Filesystem checkout root
    frontend_port: int | None = None  # Canonical frontend port
    backend_port: int | None = None  # Canonical backend port
    category: ProjectCategory = "dev"
    summitflow_hosted: bool = False
    native: bool = False
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
    lifecycle: ProjectLifecycle = "active"
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


class ProjectRetirementRequest(BaseModel):
    """Owner's explicit reason for removing a project from routine discovery."""

    reason: str = Field(min_length=10, max_length=1000)

    @field_validator("reason")
    @classmethod
    def non_blank_reason(cls, value: str) -> str:
        reason = value.strip()
        if len(reason) < 10:
            raise ValueError("Retirement reason must contain at least 10 characters")
        return reason


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
    lifecycle: ProjectLifecycle = "active"
    health_status: str | None = None
    active_checkpoint: CheckpointResponse | None = None
    stats: ProjectStats


class ProjectsWithStatsResponse(BaseModel):
    """Response for projects list with stats."""

    projects: list[ProjectWithStats]
    total: int


class ProjectPage(BaseModel):
    """A frontend page discovered live from the project checkout."""

    path: str
    name: str
    url: str | None = None
    port: int | None = None


class ProjectPagesResponse(BaseModel):
    """Frontend pages of a project."""

    items: list[ProjectPage]
