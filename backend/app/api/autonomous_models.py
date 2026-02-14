"""Autonomous execution models."""

from pydantic import BaseModel, Field

VALID_TASK_TYPES = ["refactor", "bug", "feature", "chore", "docs"]
VALID_MODEL_TIERS = ["standard", "advanced", "economy"]


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

    # Frequency limits
    max_tasks_per_day: int | None = Field(
        default=None, description="Maximum tasks to complete per day (null = unlimited)"
    )
    cooldown_minutes: int = Field(
        default=0, ge=0, description="Minimum gap between task dispatches (0 = no cooldown)"
    )

    # Allowed task types
    allowed_types: list[str] | None = Field(
        default=None, description="Task types allowed for autonomous execution (null = all types)"
    )

    # Model tier preference
    preferred_model_tier: str = Field(
        default="standard", description="Model tier for autonomous execution"
    )

    # Self-healing configuration
    max_self_fix_attempts: int = Field(
        default=3, ge=0, le=10, description="Max self-fix attempts before supervisor escalation"
    )
    max_supervisor_attempts: int = Field(
        default=3, ge=0, le=10, description="Max supervisor-guided attempts before blocking"
    )
    max_extensions: int = Field(
        default=3, ge=0, le=10, description="Max extension requests when retry budget exhausted"
    )

    # Auto-merge control
    auto_merge_enabled: bool = Field(
        default=True, description="Enable automatic merging of completed tasks"
    )
    require_review: bool = Field(
        default=True, description="Always run AI review before merge (even if auto_merge_enabled)"
    )

    # Quality gate configuration
    quality_gate_tools: list[str] = Field(
        default=[], description="Specific tools to run (e.g. ['ruff', 'mypy']). Empty = use mode."
    )
    quality_gate_mode: str = Field(
        default="quick", description="Quality gate mode: quick, check, or changed-only"
    )
    quality_gate_fix_enabled: bool = Field(
        default=True, description="Allow dt --fix during self-heal"
    )


VALID_QUALITY_GATE_MODES = ["quick", "check", "changed-only"]
VALID_QUALITY_GATE_TOOLS = ["pytest", "ruff", "mypy", "biome", "tsc", "sqlfluff", "squawk"]


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

    # Frequency limits
    max_tasks_per_day: int | None = None
    cooldown_minutes: int | None = Field(default=None, ge=0)

    # Allowed task types
    allowed_types: list[str] | None = None

    # Model tier preference
    preferred_model_tier: str | None = None

    # Self-healing configuration
    max_self_fix_attempts: int | None = Field(default=None, ge=0, le=10)
    max_supervisor_attempts: int | None = Field(default=None, ge=0, le=10)
    max_extensions: int | None = Field(default=None, ge=0, le=10)

    # Auto-merge control
    auto_merge_enabled: bool | None = None
    require_review: bool | None = None

    # Quality gate configuration
    quality_gate_tools: list[str] | None = None
    quality_gate_mode: str | None = None
    quality_gate_fix_enabled: bool | None = None
