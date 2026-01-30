"""Autocode API models and types.

Pydantic models for autocode execution requests and responses.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AutocodeRequest(BaseModel):
    """Request to start autocode execution."""

    agent_slug: str | None = Field(
        default=None,
        description="Agent Hub agent slug (e.g., 'coder', 'planner'). Required.",
    )
    dry_run: bool = Field(default=False, description="If true, validate but don't execute")


class AutocodeResponse(BaseModel):
    """Response from autocode execution start."""

    execution_id: str = Field(description="Unique execution ID for status polling")
    task_id: str = Field(description="Task being executed")
    subtask_id: str = Field(description="Current subtask being executed")
    status: str = Field(description="Execution status: pending, running, completed, failed")
    message: str | None = Field(default=None, description="Status message")


class ExecutionStatusResponse(BaseModel):
    """Response for execution status check."""

    execution_id: str
    task_id: str
    subtask_id: str | None
    status: str
    started_at: str | None
    completed_at: str | None
    retries: int
    evidence: dict[str, Any] | None = None


class ExecuteRequest(BaseModel):
    """Request to start orchestrator execution."""

    worker_id: str | None = Field(default=None, description="Optional worker ID for claiming")
    lock_duration_minutes: int = Field(default=60, description="Lock duration in minutes")


class ExecuteResponse(BaseModel):
    """Response from execute API."""

    execution_id: str = Field(description="Celery task ID for tracking")
    task_id: str = Field(description="Task being executed")
    status: str = Field(description="queued, running, completed, failed")
    message: str | None = Field(default=None, description="Status message")


# Valid statuses for execution
EXECUTABLE_STATUSES = {"pending", "planning", "paused", "failed"}
