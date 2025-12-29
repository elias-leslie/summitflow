"""Terminal Sessions API - REST endpoints for session management.

This module provides:
- List terminal sessions
- Create new session (server generates UUID)
- Update session metadata (name, order)
- Delete session (also kills tmux)

Sessions are global (not project-scoped) but may have a project_id
for context-aware working directory.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..services import lifecycle
from ..storage import terminal as terminal_store

router = APIRouter(tags=["Terminal Sessions"])


# ============================================================================
# Request/Response Models
# ============================================================================


class TerminalSessionResponse(BaseModel):
    """Terminal session response model."""

    id: str
    name: str
    user_id: str | None
    project_id: str | None
    working_dir: str | None
    display_order: int
    is_alive: bool
    created_at: str | None
    last_accessed_at: str | None


class TerminalSessionListResponse(BaseModel):
    """Response for listing terminal sessions."""

    items: list[TerminalSessionResponse]
    total: int


class CreateSessionRequest(BaseModel):
    """Request to create a terminal session."""

    name: str
    project_id: str | None = None
    working_dir: str | None = None


class UpdateSessionRequest(BaseModel):
    """Request to update a terminal session."""

    name: str | None = None
    display_order: int | None = None


# ============================================================================
# Helpers
# ============================================================================


def _session_to_response(session: dict[str, Any]) -> TerminalSessionResponse:
    """Convert storage session to API response."""
    return TerminalSessionResponse(
        id=session["id"],
        name=session["name"],
        user_id=session.get("user_id"),
        project_id=session.get("project_id"),
        working_dir=session.get("working_dir"),
        display_order=session["display_order"],
        is_alive=session["is_alive"],
        created_at=session["created_at"].isoformat() if session.get("created_at") else None,
        last_accessed_at=(
            session["last_accessed_at"].isoformat() if session.get("last_accessed_at") else None
        ),
    )


# ============================================================================
# Endpoints
# ============================================================================


@router.get("/api/terminal/sessions", response_model=TerminalSessionListResponse)
async def list_sessions() -> TerminalSessionListResponse:
    """List all alive terminal sessions.

    Returns only sessions where is_alive=True.
    Sessions are ordered by display_order, then created_at.
    """
    sessions = terminal_store.list_sessions(include_dead=False)

    return TerminalSessionListResponse(
        items=[_session_to_response(s) for s in sessions],
        total=len(sessions),
    )


@router.post("/api/terminal/sessions", response_model=TerminalSessionResponse)
async def create_session(request: CreateSessionRequest) -> TerminalSessionResponse:
    """Create a new terminal session.

    The session ID is generated server-side to prevent client collisions.
    Creates both the database record and the tmux session atomically.
    """
    try:
        session_id = lifecycle.create_session(
            name=request.name,
            project_id=request.project_id,
            working_dir=request.working_dir,
        )
    except lifecycle.TmuxError as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to create terminal session: {e}"
        ) from None

    session = terminal_store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=500, detail="Session created but not found") from None

    return _session_to_response(session)


@router.get("/api/terminal/sessions/{session_id}", response_model=TerminalSessionResponse)
async def get_session(session_id: str) -> TerminalSessionResponse:
    """Get a single terminal session by ID."""
    session = terminal_store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found") from None

    return _session_to_response(session)


@router.patch("/api/terminal/sessions/{session_id}", response_model=TerminalSessionResponse)
async def update_session(session_id: str, request: UpdateSessionRequest) -> TerminalSessionResponse:
    """Update terminal session metadata.

    Can update: name, display_order
    """
    # Verify session exists
    existing = terminal_store.get_session(session_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found") from None

    # Build update fields
    update_fields: dict[str, Any] = {}
    if request.name is not None:
        update_fields["name"] = request.name
    if request.display_order is not None:
        update_fields["display_order"] = request.display_order

    if not update_fields:
        return _session_to_response(existing)

    session = terminal_store.update_session(session_id, **update_fields)
    if not session:
        raise HTTPException(status_code=500, detail="Failed to update session") from None

    return _session_to_response(session)


@router.delete("/api/terminal/sessions/{session_id}")
async def delete_session(session_id: str) -> dict[str, Any]:
    """Delete a terminal session.

    Kills the tmux session and deletes the database record.
    Idempotent - returns success even if session didn't exist.
    """
    lifecycle.delete_session(session_id)
    return {"deleted": True, "id": session_id}
