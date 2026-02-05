"""Step-related Pydantic models for request/response validation.

Defines schemas for the task_subtask_steps table operations.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class StepCreate(BaseModel):
    """Request model for creating a single step."""

    step_number: int = Field(ge=1, description="1-indexed step number")
    description: str = Field(min_length=5, description="Step description")
    spec: dict[str, Any] | None = Field(default=None, description="Step implementation spec")


class StepUpdate(BaseModel):
    """Request model for updating step pass status."""

    passes: bool = Field(description="Whether step passes/is complete")


class StepResponse(BaseModel):
    """Response model for a step."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    subtask_id: str
    step_number: int
    description: str
    spec: dict[str, Any] | None
    verify_command: str | None
    expected_output: str | None
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


class StepCreateWithVerification(BaseModel):
    """Request model for creating a single step with required verification."""

    description: str = Field(min_length=1, description="Step description")
    verify_command: str = Field(
        min_length=1, description="Bash command to verify completion (exit 0 = pass)"
    )
    expected_output: str = Field(min_length=1, description="Description of what success looks like")
    spec: dict[str, Any] | None = Field(default=None, description="Step implementation spec")


class StepFieldsUpdate(BaseModel):
    """Request model for updating step fields (description only).

    NOTE: verify_command and expected_output are immutable after creation.
    Only the description field can be updated.
    """

    description: str | None = Field(default=None, min_length=1, description="Step description")
