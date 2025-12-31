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
    task_type: Literal["feature", "bug", "task"] = "task"
    parent_task_id: str | None = None
    # AI agent reliability fields
    objective: str | None = Field(default=None, description="Single measurable goal statement")
    acceptance_criteria: list["AcceptanceCriterion"] | None = Field(
        default=None, description="List of acceptance criteria (validated on create)"
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
    task_type: Literal["feature", "bug", "task"] | None = None
    parent_task_id: str | None = None
    # Implementation plan (JSON structure for /task_it and /do_it)
    plan_content: dict[str, Any] | None = None
    # Allow moving task to different project
    project_id: str | None = None
    # AI agent reliability fields
    objective: str | None = None
    acceptance_criteria: list["AcceptanceCriterion"] | None = None


class TaskStatusUpdate(BaseModel):
    """Request model for updating task status."""

    status: str  # pending, running, paused, failed, completed, pending_review, cancelled
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
    # AI agent reliability fields (added for TDD architecture coherence)
    objective: str | None = None
    acceptance_criteria: list[AcceptanceCriterion] | None = None
    current_phase: str | None = None
    verification_result: dict[str, Any] | None = None
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


class CriterionVerifyRequest(BaseModel):
    """Request model for verifying a criterion."""

    verified_by: Literal["opus", "test", "human"]
    notes: str | None = None


class CriterionLinkTestRequest(BaseModel):
    """Request model for linking a test to a criterion."""

    test_file: str = Field(description="Path to test file")
    test_name: str = Field(description="Test function name")


class CreateTaskCriterionRequest(BaseModel):
    """Request model for creating a task-specific criterion."""

    criterion: str = Field(min_length=10, description="Criterion text")
    category: Literal["performance", "correctness", "security", "quality"] = "correctness"
    measurement: str = "test"
    threshold: str | None = None


class VerifyTaskCriterionRequest(BaseModel):
    """Request model for verifying a task criterion."""

    verified: bool = True
    verified_by: Literal["opus", "test", "human", "agent"] = "human"
