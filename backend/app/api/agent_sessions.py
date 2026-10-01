"""Agent Sessions API - Build session tracking."""

import importlib
import sqlite3
import sys
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from ..storage import agent_sessions as storage
from .backups.key_endpoints import _require_same_origin
from .monitor import require_monitor_owner

router = APIRouter()


def _managed_owner():
    """Load the same host execution-owner interface used by the existing CLI."""
    scripts = Path(__file__).resolve().parents[3] / "scripts" / "lib"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    return importlib.import_module("codex_managed_delivery")


@router.get("/managed-codex", dependencies=[Depends(require_monitor_owner)])
def managed_codex_status(response: Response, project_id: str | None = None) -> dict:
    response.headers["Cache-Control"] = "no-store"
    try:
        return _managed_owner().operator_status(project_id=project_id)
    except (ValueError, OSError, sqlite3.Error, RuntimeError) as error:
        raise HTTPException(status_code=503, detail="Managed Codex local owner unavailable") from error


@router.post("/{project_id}/managed-codex/{action}", dependencies=[Depends(require_monitor_owner)])
def managed_codex_action(project_id: str, action: Literal["disable", "enable", "drain", "check-update", "stage-update", "qualify-update", "promote-update", "rollback-update"], request: Request, response: Response) -> dict:
    _require_same_origin(request)
    response.headers["Cache-Control"] = "no-store"
    try:
        return _managed_owner().operator_action(action, project_id=project_id)
    except ValueError as error:
        update_error = getattr(_managed_owner(), "ManagedUpdateError", type(None))
        if isinstance(error, update_error):
            raise HTTPException(status_code=409, detail=f"Managed Codex update failed: {error.code} ({error.stage})") from error
        raise HTTPException(status_code=409, detail="Managed Codex owner or project binding unavailable") from error
    except (OSError, sqlite3.Error, RuntimeError) as error:
        raise HTTPException(status_code=503, detail="Managed Codex local owner unavailable") from error


class SessionCreate(BaseModel):
    """Request model for creating a session."""

    agent_type: str  # claude, gemini, human


class SessionUpdate(BaseModel):
    """Request model for updating a session."""

    status: str | None = None
    capabilities_attempted: list[str] | None = None
    capabilities_passed: list[str] | None = None
    capabilities_failed: list[str] | None = None
    tests_run: int | None = None
    tests_passed: int | None = None
    tests_failed: int | None = None
    notes: str | None = None


class SessionEndRequest(BaseModel):
    """Request for ending a session."""

    notes: str | None = None
    git_commit_sha: str | None = None


class SessionResponse(BaseModel):
    """Response model for a session."""

    id: int
    project_id: str
    session_id: str
    agent_type: str
    status: str
    started_at: str | None = None
    ended_at: str | None = None
    capabilities_attempted: list[str] = []
    capabilities_passed: list[str] = []
    capabilities_failed: list[str] = []
    tests_run: int = 0
    tests_passed: int = 0
    tests_failed: int = 0
    notes: str | None = None
    git_commit_sha: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


@router.get("/{project_id}/sessions", response_model=list[SessionResponse])
async def list_sessions(project_id: str) -> list[SessionResponse]:
    """List all sessions for a project."""
    sessions_list = storage.list_sessions(project_id)
    return [SessionResponse(**s) for s in sessions_list]


@router.get("/{project_id}/sessions/recent", response_model=list[SessionResponse])
async def get_recent_sessions(project_id: str) -> list[SessionResponse]:
    """Get the last 3 sessions with notes (for handoff context)."""
    sessions_list = storage.get_recent_sessions(project_id, limit=3)
    return [SessionResponse(**s) for s in sessions_list]


@router.get("/{project_id}/sessions/{session_id}", response_model=SessionResponse)
async def get_session(project_id: str, session_id: str) -> SessionResponse:
    """Get a specific session."""
    session = storage.get_session(project_id, session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    return SessionResponse(**session)


@router.post("/{project_id}/sessions", response_model=SessionResponse)
async def create_session(project_id: str, body: SessionCreate) -> SessionResponse:
    """Create a new agent build session."""
    session = storage.create_session(project_id, body.agent_type)
    return SessionResponse(**session)


@router.patch("/{project_id}/sessions/{session_id}", response_model=SessionResponse)
async def update_session(project_id: str, session_id: str, body: SessionUpdate) -> SessionResponse:
    """Update a session (notes, stats, capabilities)."""
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    session = storage.update_session(project_id, session_id, **updates)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    return SessionResponse(**session)


@router.post("/{project_id}/sessions/{session_id}/end", response_model=SessionResponse)
async def end_session(project_id: str, session_id: str, body: SessionEndRequest) -> SessionResponse:
    """End a session (mark as completed with handoff notes)."""
    session = storage.end_session(
        project_id,
        session_id,
        notes=body.notes,
        git_commit_sha=body.git_commit_sha,
    )
    if not session:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    return SessionResponse(**session)
