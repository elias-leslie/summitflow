"""Task-related Pydantic models for request/response validation.

Extracted from app/api/tasks.py for reuse across the codebase.
"""

import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


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
    acceptance_criteria: list["AcceptanceCriterion"] | None = Field(
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
    acceptance_criteria: list["AcceptanceCriterion"] | None = None
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
    reason: str | None = None  # Completion reason (stored in progress_log)
    # NOTE: force flag removed - gates cannot be bypassed, complete the work instead


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
    """Acceptance criterion for AI agent reliability.

    Each criterion must be specific, measurable, and verifiable.
    The id must match pattern ac-NNN (e.g., ac-001, ac-012).
    """

    id: str = Field(description="Unique ID in format ac-NNN")
    criterion: str = Field(min_length=10, description="Specific measurable condition")
    category: Literal["performance", "correctness", "security", "quality"] = Field(
        default="correctness", description="Category of the criterion"
    )
    measurement: str = Field(
        default="test", description="How to verify: test, metric, tool, manual"
    )
    threshold: str | None = Field(
        default=None, description="Specific value or condition (e.g., '<200ms', '100%')"
    )
    test_file: str | None = Field(default=None, description="Test file path when agent writes test")
    test_name: str | None = Field(
        default=None, description="Test function name when agent writes test"
    )
    verified: bool = Field(default=False, description="Whether criterion has been verified")
    verified_at: datetime | None = Field(default=None, description="When criterion was verified")
    verified_by: Literal["opus", "test", "human", "agent"] | None = Field(
        default=None, description="Who verified the criterion"
    )

    @field_validator("id")
    @classmethod
    def validate_id_format(cls, v: str) -> str:
        """Validate that id matches pattern ac-NNN."""
        if not re.match(r"^ac-\d{3}$", v):
            raise ValueError("id must match pattern ac-NNN (e.g., ac-001)")
        return v

    @field_validator("criterion")
    @classmethod
    def validate_criterion_not_vague(cls, v: str) -> str:
        """Basic validation that criterion is not too vague."""
        vague_patterns = ["is good", "works well", "is fast", "is efficient"]
        lower_v = v.lower()
        for pattern in vague_patterns:
            if pattern in lower_v and len(v) < 30:
                raise ValueError(f"Criterion too vague. Avoid patterns like '{pattern}'.")
        return v


# =============================================================================
# Subtask Models (for task_subtasks table)
# =============================================================================


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
    description: str = Field(min_length=5, description="Subtask description")
    steps: list[str | StepInput] = Field(
        default_factory=list, description="Steps as strings or {description, spec} objects"
    )
    display_order: int = Field(default=0, ge=0, description="Order for display")
    details: dict[str, Any] | None = Field(
        default=None, description="Rich implementation spec from plan.json (deprecated)"
    )
    depends_on: list[str] | None = Field(
        default=None,
        description="List of subtask IDs this subtask depends on (e.g., ['1.1', '1.2'])",
    )


class SubtaskResponse(BaseModel):
    """Response model for a subtask."""

    id: str
    task_id: str
    subtask_id: str
    phase: str | None
    description: str
    details: dict[str, Any] | None = None
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


# =============================================================================
# AI Enrichment Models
# =============================================================================


class EnrichmentRequest(BaseModel):
    """Request model for triggering AI task enrichment."""

    raw_request: str = Field(min_length=10, description="Natural language task description")
    priority: int | None = Field(default=None, ge=0, le=4, description="Optional priority override")
    task_type: Literal["feature", "bug", "task", "refactor", "debt", "regression"] | None = Field(
        default=None, description="Optional type override"
    )


class EnrichmentResponse(BaseModel):
    """Response model after starting enrichment."""

    task_id: str
    enrichment_status: str
    message: str


class DiscussionMessage(BaseModel):
    """A single message in a task discussion."""

    role: Literal["user", "assistant"]
    content: str
    timestamp: str


class DiscussionRequest(BaseModel):
    """Request model for discussing a task with AI."""

    message: str = Field(min_length=1, description="User message")


class DiscussionResponse(BaseModel):
    """Response model for task discussion."""

    response: str = Field(description="Agent response text")
    updated_task: "TaskResponse | None" = Field(
        default=None, description="Updated task if changes were made"
    )
    history: list[DiscussionMessage] = Field(
        default_factory=list, description="Full conversation history"
    )


class CleanupPromptRequest(BaseModel):
    """Request model for AI prompt cleanup."""

    raw_request: str = Field(min_length=5, description="Raw user input to clean up")


class CleanupPromptResponse(BaseModel):
    """Response model for prompt cleanup."""

    cleaned_prompt: str
    changes_made: list[str] = Field(default_factory=list)


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


class StartTaskRequest(BaseModel):
    """Request model for starting task execution."""

    agent_type: str  # claude or gemini
    model: str | None = None
    allow_delegation: bool = False


class ClaimTaskRequest(BaseModel):
    """Request model for claiming a task."""

    worker_id: str = Field(description="Identifier for the worker claiming the task")
    lock_minutes: int = Field(default=30, ge=1, le=480, description="Lock duration in minutes")


class CriteriaValidateRequest(BaseModel):
    """Request model for validating acceptance criteria."""

    objective: str = Field(min_length=10, description="Task objective for context")
    criteria: list[AcceptanceCriterion] = Field(description="Criteria to validate")


class CriterionFailure(BaseModel):
    """Single criterion validation failure."""

    criterion_id: str
    valid: bool
    issues: list[str] = Field(default_factory=list)
    suggestion: str | None = None


class CriteriaValidateResponse(BaseModel):
    """Response model for criteria validation."""

    valid: bool
    failures: list[CriterionFailure] = Field(default_factory=list)


class CreateTaskCriterionRequest(BaseModel):
    """Request model for creating a task-specific criterion."""

    criterion: str = Field(min_length=10, description="Criterion text")
    category: Literal["performance", "correctness", "security", "quality"] = "correctness"
    measurement: str = "test"
    threshold: str | None = None
    verify_command: str | None = Field(
        default=None, description="Bash command to verify this criterion"
    )
    verify_by: Literal["test", "opus", "human", "agent"] = "test"
    expected_output: str | None = Field(
        default=None, description="Expected output from verify_command"
    )


class VerifyTaskCriterionRequest(BaseModel):
    """Request model for verifying a task criterion."""

    verified: bool = True
    verified_by: Literal["opus", "test", "human", "agent"] = "human"


class UpdateTaskCriterionRequest(BaseModel):
    """Request model for updating a task criterion."""

    criterion: str | None = Field(default=None, min_length=10, description="Criterion text")
    category: Literal["performance", "correctness", "security", "quality"] | None = None
    verify_command: str | None = Field(
        default=None, description="Bash command to verify this criterion"
    )
    verify_by: Literal["test", "opus", "human", "agent"] | None = None
    expected_output: str | None = Field(
        default=None, description="Expected output from verify_command"
    )


# =============================================================================
# Batch Creation Models
# =============================================================================


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


# =============================================================================
# Batch Task Criteria Models
# =============================================================================


class BatchTaskCriterionCreate(BaseModel):
    """A single criterion to create in batch for a task."""

    criterion: str = Field(min_length=10, description="Criterion text")
    category: Literal["performance", "correctness", "security", "quality"] = "correctness"
    measurement: str = "test"
    threshold: str | None = None
    verify_command: str | None = Field(
        default=None, description="Bash command to verify this criterion"
    )
    verify_by: Literal["test", "opus", "human", "agent"] = "test"
    expected_output: str | None = Field(
        default=None, description="Expected output from verify_command"
    )


class BatchTaskCriteriaRequest(BaseModel):
    """Request model for batch task criteria creation."""

    items: list[BatchTaskCriterionCreate]


class BatchCriterionResult(BaseModel):
    """Result for a single criterion in batch create."""

    criterion: str  # First 50 chars for identification
    success: bool
    id: int | None = None
    criterion_id: str | None = None
    error: str | None = None


class BatchTaskCriteriaResponse(BaseModel):
    """Response model for batch task criteria creation."""

    created: list[dict[str, Any]]
    errors: list[BatchCriterionResult]
