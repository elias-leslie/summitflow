"""Base task schemas for CRUD operations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from .task_criteria import AcceptanceCriterion
    from .task_enrichment import BlockerInfo, CapabilityContext
    from .task_subtasks import SubtaskResponse, SubtaskSummary


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
    task_type: Literal["feature", "bug", "task", "refactor", "debt", "regression"] = "task"
    parent_task_id: str | None = None
    # AI agent reliability fields
    objective: str | None = Field(default=None, description="Single measurable goal statement")
    acceptance_criteria: list[AcceptanceCriterion] | None = Field(
        default=None, description="List of acceptance criteria (validated on create)"
    )
    # Pipeline v2 fields
    spirit_anti: str | None = Field(
        default=None, description="What NOT to do - failure mode to avoid"
    )
    decisions: list[dict[str, Any]] | None = Field(
        default=None, description="Implementation decisions made during planning"
    )
    constraints: list[str] | None = Field(
        default=None, description="Boundaries that must not be crossed"
    )
    done_when: list[str] | None = Field(
        default=None, description="Checklist of completion conditions"
    )
    complexity: Literal["SIMPLE", "STANDARD", "COMPLEX"] | None = Field(
        default=None, description="Task complexity tier"
    )
    autonomous: bool = Field(
        default=False,
        description="Enable autonomous execution (Flash/Opus pipeline) vs manual",
    )


class TaskUpdate(BaseModel):
    """Request model for updating a task."""

    title: str | None = None
    description: str | None = None
    branch_name: str | None = None
    pull_request_url: str | None = None
    # Issue tracking fields
    priority: int | None = Field(default=None, ge=0, le=4)
    labels: list[str] | None = None
    task_type: Literal["feature", "bug", "task", "refactor", "debt", "regression"] | None = None
    parent_task_id: str | None = None
    # Allow moving task to different project
    project_id: str | None = None
    # AI agent reliability fields
    objective: str | None = None
    acceptance_criteria: list[AcceptanceCriterion] | None = None
    # Capability linkage (FK to capabilities table)
    capability_id: int | None = None
    # Pipeline v2 fields
    spirit_anti: str | None = None
    decisions: list[dict[str, Any]] | None = None
    constraints: list[str] | None = None
    done_when: list[str] | None = None
    complexity: Literal["SIMPLE", "STANDARD", "COMPLEX"] | None = None
    autonomous: bool | None = None
    # QA workflow fields (migration 068)
    qa_status: Literal["pending", "passed", "failed", "skipped"] | None = None
    qa_issues: list[dict[str, Any]] | None = None


class TaskStatusUpdate(BaseModel):
    """Request model for updating task status."""

    status: str  # pending, running, paused, blocked, pr_created, ai_reviewing, human_review, completed, failed, cancelled
    error_message: str | None = None
    reason: str | None = None  # Completion reason (logged to events table)
    # NOTE: force flag removed - gates cannot be bypassed, complete the work instead


class TaskLogEntry(BaseModel):
    """Request model for appending to progress log."""

    entry: str


class StartTaskRequest(BaseModel):
    """Request model for starting task execution."""

    agent_type: Literal["claude", "gemini"]
    model: str | None = None
    allow_delegation: bool = False


class ClaimTaskRequest(BaseModel):
    """Request model for claiming a task."""

    worker_id: str = Field(description="Identifier for the worker claiming the task")
    lock_minutes: int = Field(default=30, ge=1, le=480, description="Lock duration in minutes")


class ValidationResultResponse(BaseModel):
    """Response model for task validation result."""

    ready: bool
    issues: list[str]
    suggestions: list[str]


class TaskResponse(BaseModel):
    """Response model for a task."""

    id: str
    project_id: str
    capability_id: int | None
    title: str
    description: str | None
    status: str
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
    # AI agent reliability fields
    objective: str | None = None
    acceptance_criteria: list[AcceptanceCriterion] | None = None
    criteria_count: int | None = None  # Count from task_criteria junction table
    current_phase: str | None = None
    verification_result: dict[str, Any] | None = None
    # Pipeline v2 fields
    spirit_anti: str | None = None
    decisions: list[dict[str, Any]] | None = None
    constraints: list[str] | None = None
    done_when: list[str] | None = None
    complexity: Literal["SIMPLE", "STANDARD", "COMPLEX"] | None = None
    # AI enrichment fields
    raw_request: str | None = None
    enrichment_status: str | None = None
    enriched_by: str | None = None
    enriched_at: str | None = None
    # Optional subtasks (when include=subtasks)
    subtasks: list[SubtaskResponse] | None = None
    # Optional capability context (when include=capability)
    capability: CapabilityContext | None = None
    # Optional blockers context (when include=blockers)
    blockers: list[BlockerInfo] | None = None
    blocked_by_incomplete: bool | None = None
    # Subtask summary (when include=subtasks or from list_ready_tasks)
    subtask_summary: SubtaskSummary | None = None
    # Autonomous execution flag
    autonomous: bool = False
    # QA workflow fields (migration 068)
    qa_status: Literal["pending", "passed", "failed", "skipped"] | None = None
    qa_signoff_at: str | None = None
    qa_signoff_by: str | None = None
    qa_issues: list[dict[str, Any]] | None = None
    # Plan workflow fields (from task_spirit)
    plan_status: Literal["draft", "pending_review", "approved", "rejected"] | None = None
    plan_approved_at: str | None = None
    plan_approved_by: str | None = None
    # Context for plan.json round-trip (from task_spirit)
    context: dict[str, Any] | None = None


class TaskListResponse(BaseModel):
    """Response model for list of tasks."""

    tasks: list[TaskResponse]
    total: int
    hints: list[str] | None = Field(default=None, description="Navigation hints for next actions")
