"""Task create and update request schemas."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from .task_criteria import AcceptanceCriterion

ExecutionModeLiteral = Literal["manual", "autonomous", "manual_only"]


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
    acceptance_criteria: list[AcceptanceCriterion] | None = Field(
        default=None, description="List of acceptance criteria (validated on create)"
    )
    # Deprecated spirit fields — accepted but ignored for backwards compatibility
    objective: str | None = Field(default=None, description="DEPRECATED: no longer stored", exclude=True)
    spirit_anti: str | None = Field(default=None, description="DEPRECATED: no longer stored", exclude=True)
    decisions: list[dict[str, Any]] | None = Field(default=None, description="DEPRECATED: no longer stored", exclude=True)
    constraints: list[str] | None = Field(default=None, description="DEPRECATED: no longer stored", exclude=True)
    # Pipeline v2 fields
    done_when: list[str] | None = Field(
        default=None, description="Checklist of completion conditions"
    )
    complexity: Literal["SIMPLE", "STANDARD", "COMPLEX"] | None = Field(
        default=None, description="Task complexity tier"
    )
    execution_mode: ExecutionModeLiteral | None = Field(
        default=None,
        description="How the task may be picked up: manual or autonomous",
    )
    autonomous: bool = Field(
        default=False,
        description="Compatibility shorthand for execution_mode='autonomous'",
    )
    ai_review: bool = Field(
        default=True,
        description="Whether to run AI review before task completion. Set False for mechanical tasks.",
    )
    auto_dispatch: bool = Field(
        default=False,
        description="Automatically dispatch to Hatchet pipeline after creation",
    )


class TaskUpdate(BaseModel):
    """Request model for updating a task."""

    title: str | None = None
    description: str | None = None
    branch_name: str | None = None
    # Issue tracking fields
    priority: int | None = Field(default=None, ge=0, le=4)
    labels: list[str] | None = None
    task_type: Literal["feature", "bug", "task", "refactor", "debt", "regression"] | None = None
    parent_task_id: str | None = None
    # Allow moving task to different project
    project_id: str | None = None
    # AI agent reliability fields
    acceptance_criteria: list[AcceptanceCriterion] | None = None
    # Capability linkage (FK to capabilities table)
    capability_id: int | None = None
    # Deprecated spirit fields — accepted but ignored for backwards compatibility
    objective: str | None = Field(default=None, description="DEPRECATED: no longer stored", exclude=True)
    spirit_anti: str | None = Field(default=None, description="DEPRECATED: no longer stored", exclude=True)
    decisions: list[dict[str, Any]] | None = Field(default=None, description="DEPRECATED: no longer stored", exclude=True)
    constraints: list[str] | None = Field(default=None, description="DEPRECATED: no longer stored", exclude=True)
    # Pipeline v2 fields
    done_when: list[str] | None = None
    complexity: Literal["SIMPLE", "STANDARD", "COMPLEX"] | None = None
    execution_mode: ExecutionModeLiteral | None = None
    autonomous: bool | None = None
    ai_review: bool | None = None
    # Agent override for autonomous execution
    agent_override: str | None = Field(
        default=None, description="Override which agent executes this task (slug from Agent Hub)"
    )
