"""Step-related Pydantic models for request/response validation.

Defines schemas for the task_subtask_steps table operations.
"""

from typing import Any

from pydantic import BaseModel, Field


class StepCreate(BaseModel):
    """Request model for creating a single step."""

    step_number: int = Field(ge=1, description="1-indexed step number")
    description: str = Field(min_length=5, description="Step description")
    spec: dict[str, Any] | None = Field(default=None, description="Step implementation spec")


class StepUpdate(BaseModel):
    """Request model for updating step pass status."""

    passes: bool = Field(description="Whether step passes/is complete")
    force: bool = Field(default=False, description="Bypass sequential gate check")


class StepResponse(BaseModel):
    """Response model for a step."""

    id: int
    subtask_id: str
    step_number: int
    description: str
    spec: dict[str, Any] | None
    passes: bool
    passed_at: str | None
    created_at: str | None


class StepSummary(BaseModel):
    """Summary of step completion for a subtask."""

    total: int
    completed: int
    progress_percent: float


class StepInput(BaseModel):
    """Input model for a step - can be simple string or object with spec."""

    description: str = Field(min_length=5, description="Step description")
    spec: dict[str, Any] | None = Field(default=None, description="Step implementation spec")


class BatchStepCreate(BaseModel):
    """Request model for batch step creation.

    Steps can be provided as:
    - List of strings (description only, backward compatible)
    - List of StepInput objects with {description, spec}
    """

    steps: list[str | StepInput] = Field(
        min_length=1, description="List of steps (strings or {description, spec} objects)"
    )


class BatchStepResponse(BaseModel):
    """Response model for batch step creation."""

    created: list[StepResponse]
    count: int


class StepInsert(BaseModel):
    """Request model for inserting a step at a specific position."""

    description: str = Field(min_length=1, description="Step description")
    spec: dict[str, Any] | None = Field(default=None, description="Step implementation spec")
