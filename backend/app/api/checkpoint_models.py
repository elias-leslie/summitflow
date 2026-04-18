"""Pydantic models for the checkpoints API."""

from __future__ import annotations

from pydantic import BaseModel


class BranchInfo(BaseModel):
    """Git branch information."""

    branch: str
    subtask_id: str
    type: str  # "task" or "subtask"


class CheckpointResponse(BaseModel):
    """Checkpoint details response."""

    task_id: str
    project_id: str
    task_branch: str
    base_branch: str
    created_at: str
    claimed_by: str
    age: str
    branches: list[BranchInfo]


class CheckpointsListResponse(BaseModel):
    """List of checkpoints response."""

    checkpoints: list[CheckpointResponse]
    total: int
