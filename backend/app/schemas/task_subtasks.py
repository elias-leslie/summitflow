"""Task subtask schemas."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class StepInput(BaseModel):
    """Input model for a step - can be simple string or object with spec."""

    description: str = Field(description="Step description")
    spec: dict[str, Any] | None = Field(default=None, description="Step implementation spec")
    verify_command: str | None = Field(
        default=None, description="Command to verify step completion"
    )
    expected_output: str | None = Field(
        default=None, description="Expected output from verify_command"
    )


class SubtaskCreate(BaseModel):
    """Request model for creating a subtask."""

    subtask_id: str = Field(description="Hierarchical ID like 1.1, 2.3")
    phase: str | None = Field(
        default=None, description="Phase: research, database, backend, frontend, testing"
    )
    subtask_type: str | None = Field(
        default=None,
        description="Subtask type for agent routing: backend, frontend, ui-design, refactor, bug-fix, test, performance, config, devops",
    )
    description: str = Field(min_length=5, description="Subtask description")
    steps: list[str | StepInput] = Field(
        default_factory=list, description="Steps as strings or {description, spec} objects"
    )
    display_order: int = Field(default=0, ge=0, description="Order for display")
    depends_on: list[str] | None = Field(
        default=None,
        description="List of subtask IDs this subtask depends on (e.g., ['1.1', '1.2'])",
    )


class SubtaskResponse(BaseModel):
    """Response model for a subtask."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    task_id: str
    subtask_id: str
    phase: str | None
    subtask_type: str | None = None
    description: str
    steps: list[str]
    passes: bool
    passed_at: str | None
    display_order: int
    created_at: str | None


class SubtaskUpdate(BaseModel):
    """Request model for updating a subtask."""

    passes: bool = Field(description="Whether subtask passes/is complete")


class SubtaskSummary(BaseModel):
    """Summary of subtask completion for a task."""

    total: int
    completed: int
    next_subtask_id: str | None
    progress_percent: float
