"""API endpoints for refactor session management.

Provides CRUD for refactor_sessions to persist baseline scan IDs
and session metadata, replacing volatile /tmp file storage.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..storage import refactor_sessions

router = APIRouter()


class CreateSessionRequest(BaseModel):
    """Request to create or update a refactor session."""

    task_id: str
    baseline_scan_id: int | None = None
    baseline_commit_sha: str | None = None
    session_id: str | None = None


class UpdateSessionRequest(BaseModel):
    """Request to update a refactor session."""

    status: str | None = None
    baseline_scan_id: int | None = None
    baseline_commit_sha: str | None = None
    final_scan_id: int | None = None
    final_commit_sha: str | None = None
    subtasks_planned: int | None = None
    subtasks_completed: int | None = None


class CompleteSessionRequest(BaseModel):
    """Request to complete a refactor session."""

    final_scan_id: int | None = None
    final_commit_sha: str | None = None
    status: str = "completed"


@router.post("/{project_id}/refactor-sessions")
def create_session(
    project_id: str,
    request: CreateSessionRequest,
) -> dict[str, Any]:
    """Create or update a refactor session.

    Uses upsert - if session exists for project+task, updates it.
    """
    session = refactor_sessions.create_refactor_session(
        project_id=project_id,
        task_id=request.task_id,
        baseline_scan_id=request.baseline_scan_id,
        baseline_commit_sha=request.baseline_commit_sha,
        session_id=request.session_id,
    )
    if not session:
        raise HTTPException(status_code=500, detail="Failed to create refactor session")
    return session


@router.get("/{project_id}/refactor-sessions/active")
def get_active_session(
    project_id: str,
) -> dict[str, Any]:
    """Get the active refactor session for a project."""
    session = refactor_sessions.get_active_refactor_session(project_id)
    if not session:
        raise HTTPException(status_code=404, detail="No active refactor session found")
    return session


@router.get("/{project_id}/refactor-sessions/{task_id}")
def get_session(
    project_id: str,
    task_id: str,
) -> dict[str, Any]:
    """Get a specific refactor session by task ID."""
    session = refactor_sessions.get_refactor_session(project_id, task_id)
    if not session:
        raise HTTPException(status_code=404, detail="Refactor session not found")
    return session


@router.patch("/{project_id}/refactor-sessions/{task_id}")
def update_session(
    project_id: str,
    task_id: str,
    request: UpdateSessionRequest,
) -> dict[str, Any]:
    """Update a refactor session."""
    updates = request.model_dump(exclude_none=True)
    session = refactor_sessions.update_refactor_session(
        project_id=project_id,
        task_id=task_id,
        **updates,
    )
    if not session:
        raise HTTPException(status_code=404, detail="Refactor session not found")
    return session


@router.post("/{project_id}/refactor-sessions/{task_id}/complete")
def complete_session(
    project_id: str,
    task_id: str,
    request: CompleteSessionRequest,
) -> dict[str, Any]:
    """Mark a refactor session as completed."""
    session = refactor_sessions.complete_refactor_session(
        project_id=project_id,
        task_id=task_id,
        final_scan_id=request.final_scan_id,
        final_commit_sha=request.final_commit_sha,
        status=request.status,
    )
    if not session:
        raise HTTPException(status_code=404, detail="Refactor session not found")
    return session
