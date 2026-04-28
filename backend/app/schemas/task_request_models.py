"""Task request schemas for status updates, logging, and worker operations."""

from __future__ import annotations

from pydantic import BaseModel, Field


class TaskStatusUpdate(BaseModel):
    """Request model for updating task status."""

    status: str  # pending, running, paused, completed, failed, cancelled
    error_message: str | None = None
    reason: str | None = None  # Completion reason (logged to events table)
    skip_gates: bool = Field(
        default=False,
        description="Skip completion gate validation (for autonomous pipeline)",
    )


class TaskLogEntry(BaseModel):
    """Request model for appending to progress log."""

    entry: str


class StartTaskRequest(BaseModel):
    """Request model for starting task execution."""

    agent_slug: str | None = Field(
        default=None,
        description="Agent Hub agent slug (e.g., 'coder', 'planner'). Required.",
    )
    allow_delegation: bool = False


class ClaimTaskRequest(BaseModel):
    """Request model for claiming a task."""

    worker_id: str = Field(description="Identifier for the worker claiming the task")
    lock_minutes: int = Field(default=30, ge=1, le=480, description="Lock duration in minutes")
