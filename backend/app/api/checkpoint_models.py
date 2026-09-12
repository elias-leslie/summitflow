"""Pydantic models for the checkpoints API."""

from __future__ import annotations

from pydantic import BaseModel


class CheckpointResponse(BaseModel):
    """Checkpoint details response."""

    task_id: str
    project_id: str
    base_branch: str
    base_commit: str | None = None
    external_origin: str | None = None
    external_request_key: str | None = None
    external_payload_digest: str | None = None
    created_at: str
    claimed_by: str
    age: str


class CheckpointsListResponse(BaseModel):
    """List of checkpoints response."""

    checkpoints: list[CheckpointResponse]
    total: int
