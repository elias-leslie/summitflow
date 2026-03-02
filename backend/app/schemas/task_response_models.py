"""Task response schemas for API output models."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .task_criteria import AcceptanceCriterion

if TYPE_CHECKING:
    from .task_enrichment import BlockerInfo, CapabilityContext
    from .task_subtasks import SubtaskResponse, SubtaskSummary


class ValidationResultResponse(BaseModel):
    """Response model for task validation result."""

    ready: bool
    issues: list[str]
    suggestions: list[str]


class WorktreeResponse(BaseModel):
    """Response model for worktree info on a task."""

    path: str
    branch: str
    is_active: bool


class TaskResponse(BaseModel):
    """Response model for a task."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    capability_id: int | None
    title: str
    description: str | None
    status: str
    error_message: str | None
    branch_name: str | None
    commits: list[str]
    total_sessions: int
    total_tokens_used: int
    created_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
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
    enriched_at: datetime | None = None
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
    # AI review gate
    ai_review: bool = True
    # Agent override for autonomous execution
    agent_override: str | None = Field(
        default=None, description="Override which agent executes this task (slug from Agent Hub)"
    )
    # QA workflow fields (migration 068)
    qa_status: Literal["pending", "passed", "failed", "skipped"] | None = None
    qa_signoff_at: datetime | None = None
    qa_signoff_by: str | None = None
    qa_issues: list[dict[str, Any]] | None = None
    # Plan workflow fields (from task_spirit)
    plan_status: Literal["draft", "pending_review", "approved", "rejected"] | None = None
    plan_approved_at: datetime | None = None
    plan_approved_by: str | None = None
    # Context for plan.json round-trip (from task_spirit)
    context: dict[str, Any] | None = None
    # Worktree info (when task has an active worktree)
    worktree: WorktreeResponse | None = None


class TaskListResponse(BaseModel):
    """Response model for list of tasks."""

    tasks: list[TaskResponse]
    total: int
    hints: list[str] | None = Field(default=None, description="Navigation hints for next actions")
