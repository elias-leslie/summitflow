"""Pipeline metrics response models."""

from pydantic import BaseModel, Field


class TaskDistribution(BaseModel):
    """Task count by status."""

    pending: int = Field(ge=0, description="Tasks in pending state")
    queue: int = Field(ge=0, description="Tasks in queue (autonomous pipeline)")
    running: int = Field(ge=0, description="Tasks currently running")
    ai_reviewing: int = Field(ge=0, description="Tasks in AI review")
    completed: int = Field(ge=0, description="Successfully completed tasks")
    blocked: int = Field(ge=0, description="Tasks blocked by dependencies or issues")
    failed: int = Field(ge=0, description="Failed tasks")
    cancelled: int = Field(ge=0, description="Cancelled tasks")
    abandoned: int = Field(ge=0, description="Abandoned tasks (rolled back)")


class Throughput(BaseModel):
    """Task throughput metrics."""

    completed_today: int = Field(ge=0, description="Tasks completed today")
    completed_this_week: int = Field(ge=0, description="Tasks completed in last 7 days")
    avg_completion_hours: float = Field(ge=0.0, description="Average hours to complete a task")


class SelfHealing(BaseModel):
    """Self-healing and retry metrics."""

    first_attempt_pass_rate: float = Field(
        ge=0.0, le=1.0, description="Rate of tasks passing on first attempt (0-1)"
    )
    avg_self_fix_attempts: float = Field(
        ge=0.0, description="Average self-fix attempts per task"
    )
    supervisor_escalation_rate: float = Field(
        ge=0.0, le=1.0, description="Rate of tasks requiring supervisor escalation (0-1)"
    )
    model_escalation_count: int = Field(
        ge=0, description="Number of tasks requiring model tier upgrade"
    )


class Verification(BaseModel):
    """Step-level verification metrics."""

    step_pass_rate: float = Field(ge=0.0, le=1.0, description="Rate of steps passing (0-1)")
    avg_retries_per_step: float = Field(ge=0.0, description="Average retries per verification step")


class PartialMerge(BaseModel):
    """Partial merge and completion metrics."""

    full_completion_rate: float = Field(
        ge=0.0, le=1.0, description="Rate of fully completed tasks (0-1)"
    )
    partial_completion_rate: float = Field(
        ge=0.0, le=1.0, description="Rate of partially completed tasks (0-1)"
    )
    total_failure_rate: float = Field(
        ge=0.0, le=1.0, description="Rate of total failures (0-1)"
    )


class Autonomous(BaseModel):
    """Autonomous execution state."""

    running_count: int = Field(ge=0, description="Number of autonomous tasks currently running")
    max_concurrent: int = Field(ge=1, le=3, description="Maximum concurrent autonomous tasks")
    queue_depth: int = Field(ge=0, description="Number of tasks in autonomous queue")
    next_scheduled: str | None = Field(
        default=None, description="ISO timestamp of next scheduled task (null if none)"
    )


class PipelineStatsResponse(BaseModel):
    """Complete pipeline statistics response."""

    task_distribution: TaskDistribution
    throughput: Throughput
    self_healing: SelfHealing
    verification: Verification
    partial_merge: PartialMerge
    autonomous: Autonomous
