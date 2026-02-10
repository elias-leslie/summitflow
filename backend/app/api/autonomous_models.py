"""Autonomous execution models."""

from datetime import datetime

from pydantic import BaseModel, Field


class AutonomousSettings(BaseModel):
    """Autonomous execution settings for a project."""

    enabled: bool = Field(default=False, description="Master switch for autonomous execution")
    frequency_minutes: int = Field(
        default=30, ge=5, le=1440, description="How often to check for work (5-1440 min)"
    )
    auto_merge_tiers: list[int] = Field(
        default=[1], description="Tiers that can auto-merge without human review"
    )
    task_types: list[str] = Field(
        default=["auto-generated"],
        description="Task labels eligible for autonomous execution",
    )
    # Schedule settings (per-project time window)
    start_hour: int = Field(
        default=0, ge=0, le=23, description="Hour (0-23) when execution can start"
    )
    end_hour: int = Field(
        default=24, ge=1, le=24, description="Hour (1-24) when execution must stop"
    )
    max_concurrent: int = Field(
        default=1, ge=1, le=3, description="Max concurrent autonomous tasks (1-3)"
    )


class AutonomousSettingsUpdate(BaseModel):
    """Request model for updating autonomous settings."""

    enabled: bool | None = None
    frequency_minutes: int | None = Field(default=None, ge=5, le=1440)
    auto_merge_tiers: list[int] | None = None
    task_types: list[str] | None = None
    # Schedule settings
    start_hour: int | None = Field(default=None, ge=0, le=23)
    end_hour: int | None = Field(default=None, ge=1, le=24)
    max_concurrent: int | None = Field(default=None, ge=1, le=3)


class IterationMetrics(BaseModel):
    """Metrics about iteration behavior."""

    avg_iterations_to_success: float = Field(
        default=0.0, description="Average iterations for completed tasks (7 days)"
    )
    exhausted_count: int = Field(
        default=0, description="Tasks that hit max_iterations without success (7 days)"
    )
    consult_count: int = Field(
        default=0, description="Times alternate model was consulted (7 days)"
    )
    handoff_count: int = Field(default=0, description="Times full handoff occurred (7 days)")
    first_try_success_rate: float = Field(
        default=0.0, description="Percentage of tasks that passed on iteration 1"
    )


class GraduationProgress(BaseModel):
    """Progress toward graduating to higher autonomy."""

    tasks_until_graduation: int = Field(default=10, description="Tasks remaining before review")
    current_approval_rate: float = Field(default=0.0, description="Current review approval rate")


class AutonomousStatus(BaseModel):
    """Current autonomous execution status."""

    enabled: bool
    last_run: datetime | None = None
    pending_tasks: int = Field(default=0, description="Auto-generated pending tasks")
    in_progress: int = Field(default=0, description="Currently running tasks")
    pending_review: int = Field(default=0, description="Tasks awaiting review")
    completed_24h: int = Field(default=0, description="Completed in last 24 hours")
    failed_24h: int = Field(default=0, description="Failed in last 24 hours")
    approval_rate: float = Field(default=0.0, description="Review approval rate (7 days)")
    auto_merge_tiers: list[int] = Field(default=[1], description="Tiers eligible for auto-merge")
    graduation: GraduationProgress = Field(default_factory=GraduationProgress)
    iteration_metrics: IterationMetrics = Field(default_factory=IterationMetrics)
