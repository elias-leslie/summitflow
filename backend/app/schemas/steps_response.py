"""Response Pydantic models for step operations.

Covers single-step, batch, and summary response bodies.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class StepResponse(BaseModel):
    """Response model for a step."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    subtask_id: str
    step_number: int
    description: str
    spec: dict[str, Any] | None
    verify_command: str | None
    passes: bool
    passed_at: datetime | None
    created_at: datetime | None
    status: str | None = Field(
        default="pending", description="Step status: pending, passed, failed, plan_defect"
    )
    fix_step_number: int | None = Field(
        default=None, description="For plan_defect: step number of the passing fix step"
    )


class StepSummary(BaseModel):
    """Summary of step completion for a subtask."""

    total: int
    completed: int
    progress_percent: float


class BatchStepResponse(BaseModel):
    """Response model for batch step creation."""

    created: list[StepResponse]
    count: int
