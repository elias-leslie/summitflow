"""Pydantic models for projects API."""

from datetime import datetime

from pydantic import BaseModel


class ProjectCreate(BaseModel):
    """Request model for creating a project."""

    id: str
    name: str
    base_url: str
    health_endpoint: str = "/health"
    root_path: str | None = None  # Filesystem path for file scanning


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


class AgentConfigResponse(BaseModel):
    """Response model for agent configuration."""

    claude_enabled: bool
    gemini_enabled: bool
    default_agent: str
    claude_model: str
    gemini_model: str

    # Component management
    component_source: str = "manual"

    # Autonomous execution
    autonomous_enabled: bool = False
    autonomous_start_hour: int = 0
    autonomous_end_hour: int = 24
    autonomous_max_concurrent: int = 1


class AgentConfigUpdate(BaseModel):
    """Request model for updating agent configuration."""

    claude_enabled: bool | None = None
    gemini_enabled: bool | None = None
    default_agent: str | None = None
    claude_model: str | None = None
    gemini_model: str | None = None

    # Component management
    component_source: str | None = None

    # Autonomous execution
    autonomous_enabled: bool | None = None


class AutomationSettings(BaseModel):
    """Automation settings for crowdsourced idea processing."""

    schedule_preset: str = "nightly"  # nightly, weekly, monthly
    cron_expression: str = "0 3 * * *"
    daily_budget_usd: float = 5.0
    primary_agent: str = "gemini"
    secondary_agent: str = "claude"
    enabled: bool = False


DEFAULT_AUTOMATION_SETTINGS = {
    "schedule_preset": "nightly",
    "cron_expression": "0 3 * * *",
    "daily_budget_usd": 5.0,
    "primary_agent": "gemini",
    "secondary_agent": "claude",
    "enabled": False,
}
