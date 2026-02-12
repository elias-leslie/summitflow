"""Autonomous execution models."""

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
