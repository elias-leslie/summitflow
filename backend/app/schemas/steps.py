"""Step-related Pydantic models for request/response validation.

Defines schemas for the task_subtask_steps table operations.
"""

from pydantic import BaseModel, Field


class StepCreate(BaseModel):
    """Request model for creating a single step."""

    step_number: int = Field(ge=1, description="1-indexed step number")
    description: str = Field(min_length=5, description="Step description")


class StepUpdate(BaseModel):
    """Request model for updating step pass status."""

    passes: bool = Field(description="Whether step passes/is complete")


class StepResponse(BaseModel):
    """Response model for a step."""

    id: int
    subtask_id: str
    step_number: int
    description: str
    passes: bool
    passed_at: str | None
    created_at: str | None


class StepSummary(BaseModel):
    """Summary of step completion for a subtask."""

    total: int
    completed: int
    progress_percent: float


class BatchStepCreate(BaseModel):
    """Request model for batch step creation."""

    descriptions: list[str] = Field(
        min_length=1, description="List of step descriptions (auto-numbered from 1)"
    )


class BatchStepResponse(BaseModel):
    """Response model for batch step creation."""

    created: list[StepResponse]
    count: int
