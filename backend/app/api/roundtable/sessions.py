"""Session management endpoints for roundtable."""

import logging
from typing import Any, Literal, cast

from fastapi import APIRouter, HTTPException

from ...services.roundtable import get_roundtable_service
from ...storage import roundtable as roundtable_storage
from .helpers import restore_session_from_db
from .models import (
    CreateSessionRequest,
    CreateSessionResponse,
    EndSessionRequest,
    EndSessionResponse,
    SessionAgentConfig,
    SessionInfo,
    ToolStats,
    UpdateSessionAgentRequest,
    UpdateSessionRequest,
    UpdateSessionResponse,
    UpdateToolsRequest,
    UpdateToolsResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()

MAX_SESSIONS_PER_PROJECT = 25


@router.post(
    "/projects/{project_id}/roundtable/sessions",
    response_model=CreateSessionResponse,
)
async def create_session(
    project_id: str,
    request: CreateSessionRequest,
) -> CreateSessionResponse:
    """Create a new roundtable session.

    Enforces a limit of 25 sessions per project. When the limit is reached,
    the oldest session (by updated_at) is automatically deleted.
    """
    service = get_roundtable_service()

    # Enforce session limit - delete oldest if at limit
    session_count = roundtable_storage.get_session_count(project_id)
    if session_count >= MAX_SESSIONS_PER_PROJECT:
        deleted_id = roundtable_storage.delete_oldest_session(project_id)
        if deleted_id:
            logger.info(f"Deleted oldest session {deleted_id} to make room")

    session = service.create_session(
        project_id,
        mode=cast(Literal["spec_driven", "quick"], request.mode),
        tools_enabled=request.tools_enabled,
    )

    # Configure write access on the executor if enabled
    if request.write_enabled:
        session.tool_executor.enable_write_access()
    session.tool_executor.yolo_mode = request.yolo_mode

    # Save to database for persistence with new fields
    roundtable_storage.save_session(
        session_id=session.id,
        project_id=project_id,
        mode=cast(Literal["spec_driven", "quick"], request.mode),
        messages=[],
        generated_features=[],
        tools_enabled=request.tools_enabled,
        write_enabled=request.write_enabled,
        yolo_mode=request.yolo_mode,
        title=request.title,
        agent_mode=request.agent_mode,
    )

    return CreateSessionResponse(
        session_id=session.id,
        project_id=project_id,
        title=request.title,
        mode=request.mode,
        agent_mode=request.agent_mode,
        status="active",
        tools_enabled=request.tools_enabled,
        write_enabled=request.write_enabled,
        yolo_mode=request.yolo_mode,
    )


@router.get("/projects/{project_id}/roundtable/sessions")
async def list_sessions(project_id: str, status: str | None = None) -> list[SessionInfo]:
    """List all roundtable sessions for a project.

    Args:
        project_id: Project ID
        status: Optional filter by status ("active", "archived")
    """
    sessions = roundtable_storage.list_sessions(project_id, status=status)
    return [
        SessionInfo(
            id=s["id"],
            project_id=s["project_id"],
            title=s.get("title"),
            status=s.get("status", "active"),
            mode=s["mode"],
            agent_mode=s.get("agent_mode", "both"),
            tools_enabled=s.get("tools_enabled", True),
            write_enabled=s.get("write_enabled", False),
            yolo_mode=s.get("yolo_mode", False),
            tool_stats=ToolStats(**s.get("tool_stats", {})) if s.get("tool_stats") else None,
            agent_override=s.get("agent_override"),
            model_override=s.get("model_override"),
            message_count=s.get("message_count", 0),
            feature_count=s.get("feature_count", 0),
            created_at=s["created_at"].isoformat() if s.get("created_at") else "",
            updated_at=s["updated_at"].isoformat() if s.get("updated_at") else "",
        )
        for s in sessions
    ]


@router.get("/projects/{project_id}/roundtable/sessions/{session_id}")
async def get_session(project_id: str, session_id: str) -> dict[str, Any]:
    """Get a roundtable session with all messages."""
    session = roundtable_storage.load_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    return {
        "id": session["id"],
        "project_id": session["project_id"],
        "mode": session["mode"],
        "tools_enabled": session.get("tools_enabled", True),
        "write_enabled": session.get("write_enabled", False),
        "yolo_mode": session.get("yolo_mode", False),
        "tool_stats": session.get(
            "tool_stats", {"total_calls": 0, "files_read": 0, "searches": 0, "writes": 0}
        ),
        "agent_override": session.get("agent_override"),
        "model_override": session.get("model_override"),
        "messages": session.get("messages", []),
        "generated_features": session.get("generated_features", []),
        "created_at": session["created_at"].isoformat() if session.get("created_at") else None,
        "updated_at": session["updated_at"].isoformat() if session.get("updated_at") else None,
    }


@router.delete("/projects/{project_id}/roundtable/sessions/{session_id}")
async def delete_session(project_id: str, session_id: str) -> dict[str, Any]:
    """Delete a roundtable session."""
    deleted = roundtable_storage.delete_session(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"deleted": True, "session_id": session_id}


@router.post("/projects/{project_id}/roundtable/sessions/{session_id}/end")
async def end_session(
    project_id: str,
    session_id: str,
    request: EndSessionRequest,
) -> EndSessionResponse:
    """End a roundtable session and optionally create a checkpoint.

    Creates a checkpoint to save the session state for later resumption.
    Updates session status to 'ended'.
    """
    service = get_roundtable_service()

    # Try to get session from memory first
    session = service.get_session(session_id)

    # If not in memory, try to restore from DB
    if session is None:
        session = restore_session_from_db(service, session_id, project_id)

    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    # End the session (creates checkpoint if requested)
    checkpoint = service.end_session(
        session=session,
        summary=request.summary,
        completed_steps=request.completed_steps,
        remaining_steps=request.remaining_steps,
        create_checkpoint=request.create_checkpoint,
    )

    # Update session status in DB
    roundtable_storage.update_session_metadata(
        session_id=session_id,
        status="ended",
    )

    return EndSessionResponse(
        session_id=session_id,
        status="ended",
        checkpoint_id=checkpoint["id"] if checkpoint else None,
        checkpoint_created=checkpoint is not None,
    )


@router.patch(
    "/projects/{project_id}/roundtable/sessions/{session_id}",
    response_model=UpdateSessionResponse,
)
async def update_session(
    project_id: str, session_id: str, request: UpdateSessionRequest
) -> UpdateSessionResponse:
    """Update a session's metadata (title, status, agent_mode)."""
    # Validate agent_mode if provided
    if request.agent_mode is not None and request.agent_mode not in ("claude", "gemini", "both"):
        raise HTTPException(
            status_code=400, detail="agent_mode must be 'claude', 'gemini', or 'both'"
        )

    # Validate status if provided
    if request.status is not None and request.status not in ("active", "archived"):
        raise HTTPException(status_code=400, detail="status must be 'active' or 'archived'")

    result = roundtable_storage.update_session_metadata(
        session_id=session_id,
        title=request.title,
        status=request.status,
        agent_mode=request.agent_mode,
    )

    if not result:
        raise HTTPException(status_code=404, detail="Session not found")

    return UpdateSessionResponse(
        id=result["id"],
        project_id=result["project_id"],
        title=result.get("title"),
        status=result.get("status", "active"),
        agent_mode=result.get("agent_mode", "both"),
        updated_at=result["updated_at"].isoformat() if result.get("updated_at") else "",
    )


@router.get("/projects/{project_id}/roundtable/sessions/{session_id}/agent-config")
async def get_session_agent_config(project_id: str, session_id: str) -> SessionAgentConfig:
    """Get agent configuration override for a session."""
    session = roundtable_storage.load_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    return SessionAgentConfig(
        agent_override=session.get("agent_override"),
        model_override=session.get("model_override"),
    )


@router.patch("/projects/{project_id}/roundtable/sessions/{session_id}/agent-config")
async def update_session_agent_config(
    project_id: str, session_id: str, request: UpdateSessionAgentRequest
) -> SessionAgentConfig:
    """Update agent configuration override for a session.

    Set agent_override to override the project's default agent (claude/gemini).
    Set model_override to override the default model for that agent.
    Set to null to clear the override and use project defaults.
    """
    session = roundtable_storage.load_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Validate agent if provided
    if request.agent_override is not None and request.agent_override not in ("claude", "gemini"):
        raise HTTPException(status_code=400, detail="agent_override must be 'claude' or 'gemini'")

    # Update session with new values
    roundtable_storage.update_agent_config(
        session_id,
        agent_override=request.agent_override,
        model_override=request.model_override,
    )

    return SessionAgentConfig(
        agent_override=request.agent_override,
        model_override=request.model_override,
    )


@router.patch(
    "/projects/{project_id}/roundtable/sessions/{session_id}/tools",
    response_model=UpdateToolsResponse,
)
async def update_tools(
    project_id: str,
    session_id: str,
    request: UpdateToolsRequest,
) -> UpdateToolsResponse:
    """Update tools access settings for a roundtable session.

    This allows enabling/disabling codebase access, write access, or YOLO mode mid-session.
    The change takes effect immediately for subsequent messages.

    - tools_enabled: Enable/disable read access (search, read files)
    - write_enabled: Enable/disable write access (edit, create, delete files)
    - yolo_mode: Enable/disable auto-approve mode (skip all permission prompts)
    """
    result = roundtable_storage.update_tools_settings(
        session_id,
        tools_enabled=request.tools_enabled,
        write_enabled=request.write_enabled,
        yolo_mode=request.yolo_mode,
    )
    if not result:
        raise HTTPException(status_code=404, detail="Session not found")

    # Also update in-memory session if it exists
    service = get_roundtable_service()
    session = service.get_session(session_id)
    if session:
        if request.tools_enabled is not None:
            session.tools_enabled = request.tools_enabled
        if request.write_enabled is not None:
            if request.write_enabled:
                session.tool_executor.enable_write_access()
            else:
                session.tool_executor.disable_write_access()
        if request.yolo_mode is not None:
            session.tool_executor.yolo_mode = request.yolo_mode

    return UpdateToolsResponse(
        session_id=session_id,
        tools_enabled=result["tools_enabled"],
        write_enabled=result["write_enabled"],
        yolo_mode=result["yolo_mode"],
        tool_stats=ToolStats(**result.get("tool_stats", {})),
    )
