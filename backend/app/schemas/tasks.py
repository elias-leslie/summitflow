"""Task-related Pydantic models for request/response validation.

Extracted from app/api/tasks.py for reuse across the codebase.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field


class TaskCreate(BaseModel):
    """Request model for creating a new task."""

    title: str
    description: str | None = None
    capability_id: int | None = None  # Database ID of capability (optional)
    # Issue tracking fields
    priority: int = Field(default=2, ge=0, le=4, description="Priority 0-4 (0=critical, 4=backlog)")
    labels: list[str] = Field(
        default_factory=list, description="Labels (complexity:small, domains:backend)"
    )
    task_type: Literal["feature", "bug", "task"] = "task"
    parent_task_id: str | None = None


class TaskUpdate(BaseModel):
    """Request model for updating a task."""

    title: str | None = None
    description: str | None = None
    branch_name: str | None = None
    pull_request_url: str | None = None
    # Issue tracking fields
    priority: int | None = Field(default=None, ge=0, le=4)
    labels: list[str] | None = None
    task_type: Literal["feature", "bug", "task"] | None = None
    parent_task_id: str | None = None
    # Implementation plan (JSON structure for /task_it and /do_it)
    plan_content: dict[str, Any] | None = None
    # Allow moving task to different project
    project_id: str | None = None


class TaskStatusUpdate(BaseModel):
    """Request model for updating task status."""

    status: str  # pending, running, paused, failed, completed
    error_message: str | None = None
    force: bool = False  # Bypass criteria validation on close


class TaskLogEntry(BaseModel):
    """Request model for appending to progress log."""

    entry: str


class DependencyCreate(BaseModel):
    """Request model for creating a dependency."""

    depends_on_task_id: str
    dependency_type: Literal["blocks", "discovered-from"] = "blocks"


class ValidationResultResponse(BaseModel):
    """Response model for task validation result."""

    ready: bool
    issues: list[str]
    suggestions: list[str]


class DependencyResponse(BaseModel):
    """Response model for a dependency."""

    id: int
    task_id: str
    depends_on_task_id: str
    dependency_type: str
    created_at: str | None
    depends_on_title: str | None = None
    depends_on_status: str | None = None


class AcceptanceCriterion(BaseModel):
    """Acceptance criterion for a feature."""

    id: str
    description: str
    passes: bool = False


class CapabilityContext(BaseModel):
    """Capability context for a task."""

    id: int  # Database ID
    capability_id: str  # String ID like login, password-reset
    name: str
    criteria_passed: int
    criteria_total: int
    acceptance_criteria: list[AcceptanceCriterion] | None = None


class BlockerInfo(BaseModel):
    """Information about a blocking task."""

    id: str
    title: str
    status: str
    priority: int


class TaskResponse(BaseModel):
    """Response model for a task."""

    id: str
    project_id: str
    capability_id: int | None
    title: str
    description: str | None
    status: str
    current_criterion_id: str | None
    spec_content: str | None
    plan_content: dict[str, Any] | None
    progress_log: str | None
    error_message: str | None
    branch_name: str | None
    commits: list[str]
    pull_request_url: str | None
    total_sessions: int
    total_tokens_used: int
    created_at: str | None
    started_at: str | None
    completed_at: str | None
    # Issue tracking fields
    priority: int
    labels: list[str]
    task_type: str
    parent_task_id: str | None
    # Optional capability context (when include=capability)
    capability: CapabilityContext | None = None
    # Optional blockers context (when include=blockers)
    blockers: list[BlockerInfo] | None = None
    blocked_by_incomplete: bool | None = None


class TaskListResponse(BaseModel):
    """Response model for list of tasks."""

    tasks: list[TaskResponse]
    total: int


class StartTaskRequest(BaseModel):
    """Request model for starting task execution."""

    agent_type: str  # claude or gemini
    model: str | None = None
    allow_delegation: bool = False
