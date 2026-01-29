"""Task batch operation schemas."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

from .task_subtasks import SubtaskCreate

if TYPE_CHECKING:
    from .task_base import TaskResponse


class BatchTaskCreate(BaseModel):
    """Request model for a single task in batch creation."""

    title: str
    description: str | None = None
    capability_id: int | None = None  # Database ID of capability (optional)
    priority: int = Field(default=2, ge=0, le=4)
    labels: list[str] = Field(default_factory=list)
    task_type: Literal["feature", "bug", "task", "refactor", "debt", "regression"] = "task"
    parent_task_id: str | None = None
    objective: str | None = None
    # Pipeline v2 fields
    spirit_anti: str | None = None
    decisions: list[dict[str, Any]] | None = None
    constraints: list[str] | None = None
    done_when: list[str] | None = None
    complexity: Literal["SIMPLE", "STANDARD", "COMPLEX"] | None = None
    subtasks: list[SubtaskCreate] | None = Field(
        default=None, description="Nested subtasks to create with the task"
    )
    autonomous: bool = Field(
        default=False,
        description="Enable autonomous execution for this task",
    )


class BatchTaskRequest(BaseModel):
    """Request model for batch task creation."""

    items: list[BatchTaskCreate]


class BatchTaskResult(BaseModel):
    """Result for a single item in batch task create."""

    title: str
    success: bool
    id: str | None = None
    error: str | None = None


class BatchTaskResponse(BaseModel):
    """Response model for batch task creation."""

    created: list[TaskResponse]
    errors: list[BatchTaskResult]
