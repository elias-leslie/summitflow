"""Checkpoints API - Pause and resume agent sessions.

This module provides REST API endpoints for the checkpoint system:
- GET /projects/{project_id}/checkpoints - List checkpoints
- GET /projects/{project_id}/checkpoints/{session_id} - Get latest checkpoint for session
- POST /projects/{project_id}/checkpoints - Create a checkpoint
- POST /projects/{project_id}/checkpoints/{id}/resume - Generate resume prompt
- DELETE /projects/{project_id}/checkpoints/{id} - Delete a checkpoint
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ..services.memory import CheckpointService

router = APIRouter()


class CreateCheckpointRequest(BaseModel):
    """Request model for creating a checkpoint."""

    session_id: str
    agent_type: str
    current_action: str | None = None
    question: str | None = None
    options: list[dict[str, Any]] | None = None
    recommendation: str | None = None
    completed_steps: list[str] | None = None
    remaining_steps: list[str] | None = None
    files_modified: list[str] | None = None
    decisions_made: list[dict[str, Any]] | None = None
    conversation_summary: str | None = None
    context_snapshot: dict[str, Any] | None = None
    tokens_used: int | None = None


class CheckpointResponse(BaseModel):
    """Response model for a checkpoint."""

    id: str
    project_id: str
    session_id: str
    agent_type: str
    current_action: str | None
    question: str | None
    options: list[dict[str, Any]] | None
    recommendation: str | None
    completed_steps: list[str] | None
    remaining_steps: list[str] | None
    files_modified: list[str] | None
    decisions_made: list[dict[str, Any]] | None
    conversation_summary: str | None
    context_snapshot: dict[str, Any] | None
    tokens_used: int | None
    created_at: str | None


class ResumePromptResponse(BaseModel):
    """Response model for resume prompt."""

    checkpoint_id: str
    session_id: str
    resume_prompt: str


@router.get("/{project_id}/checkpoints")
async def list_checkpoints(
    project_id: str,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> list[dict[str, Any]]:
    """List checkpoints for a project.

    Returns checkpoints sorted by created_at descending (newest first).
    """
    service = CheckpointService(project_id=project_id)
    return service.list_checkpoints(limit=limit, offset=offset)


@router.get("/{project_id}/checkpoints/session/{session_id}")
async def get_checkpoint_by_session(
    project_id: str,
    session_id: str,
) -> dict[str, Any]:
    """Get the latest checkpoint for a session.

    Returns the most recent checkpoint for the specified session.
    """
    service = CheckpointService(project_id=project_id)
    checkpoint = service.get_checkpoint(session_id)

    if not checkpoint:
        raise HTTPException(status_code=404, detail="No checkpoint found for session")

    return checkpoint


@router.get("/{project_id}/checkpoints/{checkpoint_id}")
async def get_checkpoint(
    project_id: str,
    checkpoint_id: str,
) -> dict[str, Any]:
    """Get a checkpoint by ID."""
    service = CheckpointService(project_id=project_id)
    checkpoint = service.get_checkpoint_by_id(checkpoint_id)

    if not checkpoint:
        raise HTTPException(status_code=404, detail="Checkpoint not found")

    return checkpoint


@router.post("/{project_id}/checkpoints", response_model=CheckpointResponse)
async def create_checkpoint(
    project_id: str,
    request: CreateCheckpointRequest,
) -> CheckpointResponse:
    """Create a checkpoint to save current agent state.

    Saves the current state of an agent session so it can be
    resumed later without losing context.
    """
    service = CheckpointService(project_id=project_id)

    checkpoint = service.create_checkpoint(
        session_id=request.session_id,
        agent_type=request.agent_type,
        current_action=request.current_action,
        question=request.question,
        options=request.options,
        recommendation=request.recommendation,
        completed_steps=request.completed_steps,
        remaining_steps=request.remaining_steps,
        files_modified=request.files_modified,
        decisions_made=request.decisions_made,
        conversation_summary=request.conversation_summary,
        context_snapshot=request.context_snapshot,
        tokens_used=request.tokens_used,
    )

    # Add None check for pyright
    if not checkpoint:
        raise HTTPException(status_code=500, detail="Failed to create checkpoint")

    return CheckpointResponse(**checkpoint)


@router.post("/{project_id}/checkpoints/{checkpoint_id}/resume")
async def generate_resume_prompt(
    project_id: str,
    checkpoint_id: str,
    include_context: bool = Query(True, description="Include context snapshot"),
) -> ResumePromptResponse:
    """Generate a resume prompt from a checkpoint.

    Returns a formatted prompt that can be given to an agent
    to resume work from where it left off.
    """
    service = CheckpointService(project_id=project_id)
    checkpoint = service.get_checkpoint_by_id(checkpoint_id)

    if not checkpoint:
        raise HTTPException(status_code=404, detail="Checkpoint not found")

    resume_prompt = service.generate_resume_prompt(
        checkpoint=checkpoint,
        include_context=include_context,
    )

    return ResumePromptResponse(
        checkpoint_id=checkpoint_id,
        session_id=checkpoint["session_id"],
        resume_prompt=resume_prompt,
    )


@router.delete("/{project_id}/checkpoints/{checkpoint_id}")
async def delete_checkpoint(
    project_id: str,
    checkpoint_id: str,
) -> dict[str, bool]:
    """Delete a checkpoint.

    Returns success status.
    """
    service = CheckpointService(project_id=project_id)
    deleted = service.delete_checkpoint(checkpoint_id)

    if not deleted:
        raise HTTPException(status_code=404, detail="Checkpoint not found")

    return {"deleted": True}
