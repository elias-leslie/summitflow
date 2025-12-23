"""Roundtable API endpoints for multi-agent collaboration.

Provides REST endpoints for creating sessions, sending messages,
and generating features from conversations.
"""

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..services.roundtable import (
    RoundtableMessage,
    RoundtableService,
    RoundtableSession,
    TargetAgent,
    current_session_id,
    get_roundtable_service,
)
from ..services.roundtable_permissions import permission_manager
from ..storage import extraction_prompts as extraction_prompts_storage
from ..storage import roundtable as roundtable_storage

logger = logging.getLogger(__name__)


def _restore_session_from_db(
    service: RoundtableService,
    session_id: str,
    project_id: str,
) -> RoundtableSession | None:
    """Load a session from DB and restore it in memory with all state.

    Helper to avoid duplicating session restoration logic across endpoints.
    Restores messages, agent config, and SDK session IDs.

    Args:
        service: RoundtableService instance
        session_id: Session ID to load
        project_id: Project ID for validation

    Returns:
        Restored RoundtableSession or None if not found
    """
    from datetime import datetime

    db_session = roundtable_storage.load_session(session_id)
    if not db_session:
        return None

    # Create session in memory with agent config
    session = service.create_session(
        project_id,
        mode=db_session.get("mode", "quick"),
    )
    session.id = session_id
    session.agent_override = db_session.get("agent_override")
    session.model_override = db_session.get("model_override")

    # Restore SDK session IDs for context resume
    session.claude_sdk_session_id = db_session.get("claude_sdk_session_id")
    session.gemini_sdk_session_id = db_session.get("gemini_sdk_session_id")

    # Restore messages
    for msg_data in db_session.get("messages", []):
        msg = RoundtableMessage(
            id=msg_data.get("id", ""),
            agent=msg_data.get("agent", "user"),
            content=msg_data.get("content", ""),
            timestamp=datetime.fromisoformat(
                msg_data.get("timestamp", datetime.utcnow().isoformat())
            ),
            tokens_used=msg_data.get("tokens_used", 0),
            model=msg_data.get("model"),
        )
        session.messages.append(msg)

    service._sessions[session_id] = session
    return session


router = APIRouter()


# ============================================================================
# Request/Response Models
# ============================================================================


class CreateSessionRequest(BaseModel):
    """Request to create a new roundtable session."""

    title: str | None = None  # Optional session title
    mode: str = "quick"  # "spec_driven" or "quick"
    agent_mode: str = "both"  # "claude", "gemini", or "both"
    tools_enabled: bool = True  # Enable codebase read access by default
    write_enabled: bool = False  # Disable write access by default
    yolo_mode: bool = False  # Disable YOLO mode by default


class CreateSessionResponse(BaseModel):
    """Response after creating a session."""

    session_id: str
    project_id: str
    title: str | None = None
    mode: str
    agent_mode: str = "both"
    status: str = "active"
    tools_enabled: bool = True
    write_enabled: bool = False
    yolo_mode: bool = False


class ToolStats(BaseModel):
    """Tool usage statistics."""

    total_calls: int = 0
    files_read: int = 0
    searches: int = 0
    writes: int = 0


class UpdateToolsRequest(BaseModel):
    """Request to update tools settings."""

    tools_enabled: bool | None = None  # Enable/disable read tools
    write_enabled: bool | None = None  # Enable/disable write tools
    yolo_mode: bool | None = None  # Enable/disable YOLO mode (auto-approve all)


class UpdateToolsResponse(BaseModel):
    """Response after updating tools settings."""

    session_id: str
    tools_enabled: bool
    write_enabled: bool
    yolo_mode: bool
    tool_stats: ToolStats


class MessageRequest(BaseModel):
    """Request to send a message in a session."""

    message: str
    target: TargetAgent = "both"  # "claude", "gemini", or "both"


class MessageResponse(BaseModel):
    """Single message in response."""

    id: str
    agent: str
    content: str
    timestamp: str
    tokens_used: int = 0
    model: str | None = None


class SendMessageResponse(BaseModel):
    """Response after sending a message."""

    user_message: MessageResponse
    responses: list[MessageResponse]


# Extraction Prompts Models
class ExtractionPromptConfig(BaseModel):
    """Configuration for an extraction prompt."""

    prompt_type: str
    prompt_text: str
    primary_agent: str = "claude"
    primary_model: str = "claude-sonnet-4-5"
    verification_enabled: bool = False
    verification_agent: str | None = None
    verification_model: str | None = None
    verification_prompt: str | None = None
    is_default: bool = False
    created_at: str | None = None
    updated_at: str | None = None


class UpdateExtractionPromptRequest(BaseModel):
    """Request to update an extraction prompt."""

    prompt_text: str
    primary_agent: str = "claude"
    primary_model: str = "claude-sonnet-4-5"
    verification_enabled: bool = False
    verification_agent: str | None = None
    verification_model: str | None = None
    verification_prompt: str | None = None


class ExtractionPromptsExport(BaseModel):
    """Export format for extraction prompts."""

    project_id: str
    exported_at: str
    prompts: list[ExtractionPromptConfig]


class SessionInfo(BaseModel):
    """Session info for listing."""

    id: str
    project_id: str
    title: str | None = None
    status: str = "active"
    mode: str
    agent_mode: str = "both"
    tools_enabled: bool = True
    write_enabled: bool = False
    yolo_mode: bool = False
    tool_stats: ToolStats | None = None
    agent_override: str | None = None
    model_override: str | None = None
    message_count: int
    feature_count: int
    created_at: str
    updated_at: str


class UpdateSessionRequest(BaseModel):
    """Request to update a session's metadata."""

    title: str | None = None
    status: str | None = None  # "active" or "archived"
    agent_mode: str | None = None  # "claude", "gemini", or "both"


class UpdateSessionResponse(BaseModel):
    """Response after updating a session."""

    id: str
    project_id: str
    title: str | None = None
    status: str
    agent_mode: str
    updated_at: str


class SessionAgentConfig(BaseModel):
    """Agent configuration for a session."""

    agent_override: str | None = None
    model_override: str | None = None


class UpdateSessionAgentRequest(BaseModel):
    """Request to update session agent configuration."""

    agent_override: str | None = None
    model_override: str | None = None


class PermissionResolution(BaseModel):
    """Request to resolve a pending permission."""

    approved: bool


class PermissionResolutionResponse(BaseModel):
    """Response after resolving a permission."""

    status: str
    approved: bool


# ============================================================================
# Permission Helpers
# ============================================================================


def _get_preview(tool_name: str, tool_args: dict[str, Any]) -> str:
    """Generate a human-readable preview of a tool operation.

    Returns a truncated preview (max 500 chars) suitable for display
    in the permission dialog.

    Args:
        tool_name: Name of the tool being called
        tool_args: Arguments passed to the tool

    Returns:
        Human-readable preview string
    """
    if tool_name == "write_file":
        content = tool_args.get("content", "")
        path = tool_args.get("file_path", "unknown")
        preview = f"File: {path}\n\nContent:\n{content[:400]}"
        if len(content) > 400:
            preview += "..."
        return preview[:500]

    elif tool_name == "edit_file":
        old = tool_args.get("old_string", "")[:150]
        new = tool_args.get("new_string", "")[:150]
        path = tool_args.get("file_path", "unknown")
        preview = f"File: {path}\n\nReplace:\n{old}\n\nWith:\n{new}"
        return preview[:500]

    elif tool_name == "delete_file":
        path = tool_args.get("file_path", "unknown")
        return f"Delete file: {path}"

    elif tool_name == "create_directory":
        path = tool_args.get("path", "unknown")
        return f"Create directory: {path}"

    # Generic fallback
    preview = str(tool_args)
    if len(preview) > 500:
        preview = preview[:497] + "..."
    return preview


# ============================================================================
# Endpoints
# ============================================================================


MAX_SESSIONS_PER_PROJECT = 25


@router.post(
    "/projects/{project_id}/roundtable/sessions",
    response_model=CreateSessionResponse,
)
async def create_session(
    project_id: str,
    request: CreateSessionRequest,
):
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
        mode=request.mode,
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
        mode=request.mode,
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
async def get_session(project_id: str, session_id: str):
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
async def delete_session(project_id: str, session_id: str):
    """Delete a roundtable session."""
    deleted = roundtable_storage.delete_session(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"deleted": True, "session_id": session_id}


class EndSessionRequest(BaseModel):
    """Request to end a session with optional checkpoint."""

    summary: str | None = None
    completed_steps: list[str] | None = None
    remaining_steps: list[str] | None = None
    create_checkpoint: bool = True


class EndSessionResponse(BaseModel):
    """Response after ending a session."""

    session_id: str
    status: str
    checkpoint_id: str | None = None
    checkpoint_created: bool = False


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
        session = _restore_session_from_db(service, session_id, project_id)

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
):
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


@router.post(
    "/projects/{project_id}/roundtable/sessions/{session_id}/permissions/{permission_id}",
    response_model=PermissionResolutionResponse,
)
async def resolve_permission(
    project_id: str,
    session_id: str,
    permission_id: str,
    request: PermissionResolution,
):
    """Resolve a pending permission request.

    Called by the frontend when the user approves or denies a write tool operation.
    The pending permission must exist and not have timed out.

    Args:
        project_id: Project ID (for URL consistency)
        session_id: Session ID (for URL consistency)
        permission_id: The ID of the pending permission to resolve
        request: Contains the approval decision

    Returns:
        Success response with status and approved value

    Raises:
        HTTPException: 404 if permission not found or expired
    """
    success = permission_manager.resolve(permission_id, request.approved)
    if not success:
        raise HTTPException(
            status_code=404,
            detail="Permission request not found or expired",
        )

    logger.info(
        "permission_resolved",
        extra={
            "permission_id": permission_id,
            "session_id": session_id,
            "approved": request.approved,
        },
    )

    return PermissionResolutionResponse(
        status="resolved",
        approved=request.approved,
    )


@router.post(
    "/projects/{project_id}/roundtable/sessions/{session_id}/messages",
    response_model=SendMessageResponse,
)
async def send_message(
    project_id: str,
    session_id: str,
    request: MessageRequest,
):
    """Send a message in a roundtable session."""
    service = get_roundtable_service()

    # Get or recreate session
    session = service.get_session(session_id)
    if not session:
        session = _restore_session_from_db(service, session_id, project_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

    # Route message to agents
    responses = []
    async for response in service.route_message_async(session, request.message, request.target):
        responses.append(response)

    # Get the user message (second to last in session)
    user_msg = session.messages[-len(responses) - 1]

    # Persist to database
    messages_data = [
        {
            "id": m.id,
            "agent": m.agent,
            "content": m.content,
            "timestamp": m.timestamp.isoformat(),
            "tokens_used": m.tokens_used,
            "model": m.model,
        }
        for m in session.messages
    ]
    roundtable_storage.save_session(
        session_id=session_id,
        project_id=project_id,
        mode=session.mode,
        messages=messages_data,
        generated_features=None,  # Don't overwrite existing features
    )

    return SendMessageResponse(
        user_message=MessageResponse(
            id=user_msg.id,
            agent=user_msg.agent,
            content=user_msg.content,
            timestamp=user_msg.timestamp.isoformat(),
            tokens_used=user_msg.tokens_used,
            model=user_msg.model,
        ),
        responses=[
            MessageResponse(
                id=r.id,
                agent=r.agent,
                content=r.content,
                timestamp=r.timestamp.isoformat(),
                tokens_used=r.tokens_used,
                model=r.model,
            )
            for r in responses
        ],
    )


# ============================================================================
# Extraction Prompts Endpoints
# ============================================================================


@router.get(
    "/projects/{project_id}/roundtable/extraction-prompts",
    response_model=list[ExtractionPromptConfig],
)
async def list_extraction_prompts(project_id: str) -> list[ExtractionPromptConfig]:
    """List all extraction prompts for a project.

    Returns all prompt types with their current configuration.
    If a custom prompt exists, it's returned; otherwise, the default is used.
    The is_default flag indicates whether the prompt is using default configuration.
    """
    prompts = extraction_prompts_storage.get_all_extraction_prompts(project_id)
    return [
        ExtractionPromptConfig(
            prompt_type=p["prompt_type"],
            prompt_text=p["prompt_text"],
            primary_agent=p.get("primary_agent", "claude"),
            primary_model=p.get("primary_model", "claude-sonnet-4-5"),
            verification_enabled=p.get("verification_enabled", False),
            verification_agent=p.get("verification_agent"),
            verification_model=p.get("verification_model"),
            verification_prompt=p.get("verification_prompt"),
            is_default=p.get("is_default", True),
            created_at=p.get("created_at").isoformat() if p.get("created_at") else None,
            updated_at=p.get("updated_at").isoformat() if p.get("updated_at") else None,
        )
        for p in prompts
    ]


# NOTE: Export must come BEFORE {prompt_type} routes to avoid route conflict
@router.get(
    "/projects/{project_id}/roundtable/extraction-prompts/export",
)
async def export_extraction_prompts(
    project_id: str, format: str = "json"
) -> ExtractionPromptsExport:
    """Export all extraction prompts for backup/sharing.

    Currently only JSON format is supported.
    """
    if format != "json":
        raise HTTPException(status_code=400, detail="Only 'json' format is currently supported")

    from datetime import datetime

    prompts = extraction_prompts_storage.get_all_extraction_prompts(project_id)

    return ExtractionPromptsExport(
        project_id=project_id,
        exported_at=datetime.utcnow().isoformat(),
        prompts=[
            ExtractionPromptConfig(
                prompt_type=p["prompt_type"],
                prompt_text=p["prompt_text"],
                primary_agent=p.get("primary_agent", "claude"),
                primary_model=p.get("primary_model", "claude-sonnet-4-5"),
                verification_enabled=p.get("verification_enabled", False),
                verification_agent=p.get("verification_agent"),
                verification_model=p.get("verification_model"),
                verification_prompt=p.get("verification_prompt"),
                is_default=p.get("is_default", True),
                created_at=p.get("created_at").isoformat() if p.get("created_at") else None,
                updated_at=p.get("updated_at").isoformat() if p.get("updated_at") else None,
            )
            for p in prompts
        ],
    )


@router.get(
    "/projects/{project_id}/roundtable/extraction-prompts/{prompt_type}",
    response_model=ExtractionPromptConfig,
)
async def get_extraction_prompt(project_id: str, prompt_type: str) -> ExtractionPromptConfig:
    """Get a specific extraction prompt by type.

    Valid prompt types: feature_extraction, vision_extraction, goals_extraction
    """
    valid_types = ["feature_extraction", "vision_extraction", "goals_extraction"]
    if prompt_type not in valid_types:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid prompt type. Must be one of: {', '.join(valid_types)}",
        )

    prompt = extraction_prompts_storage.get_extraction_prompt(project_id, prompt_type)
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt type not found")

    return ExtractionPromptConfig(
        prompt_type=prompt["prompt_type"],
        prompt_text=prompt["prompt_text"],
        primary_agent=prompt.get("primary_agent", "claude"),
        primary_model=prompt.get("primary_model", "claude-sonnet-4-5"),
        verification_enabled=prompt.get("verification_enabled", False),
        verification_agent=prompt.get("verification_agent"),
        verification_model=prompt.get("verification_model"),
        verification_prompt=prompt.get("verification_prompt"),
        is_default=prompt.get("is_default", True),
        created_at=prompt.get("created_at").isoformat() if prompt.get("created_at") else None,
        updated_at=prompt.get("updated_at").isoformat() if prompt.get("updated_at") else None,
    )


@router.put(
    "/projects/{project_id}/roundtable/extraction-prompts/{prompt_type}",
    response_model=ExtractionPromptConfig,
)
async def update_extraction_prompt(
    project_id: str, prompt_type: str, request: UpdateExtractionPromptRequest
) -> ExtractionPromptConfig:
    """Create or update an extraction prompt.

    Valid prompt types: feature_extraction, vision_extraction, goals_extraction
    """
    valid_types = ["feature_extraction", "vision_extraction", "goals_extraction"]
    if prompt_type not in valid_types:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid prompt type. Must be one of: {', '.join(valid_types)}",
        )

    valid_agents = ["claude", "gemini"]
    if request.primary_agent not in valid_agents:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid primary_agent. Must be one of: {', '.join(valid_agents)}",
        )

    if (
        request.verification_enabled
        and request.verification_agent
        and request.verification_agent not in valid_agents
    ):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid verification_agent. Must be one of: {', '.join(valid_agents)}",
        )

    result = extraction_prompts_storage.upsert_extraction_prompt(
        project_id=project_id,
        prompt_type=prompt_type,
        prompt_text=request.prompt_text,
        primary_agent=request.primary_agent,
        primary_model=request.primary_model,
        verification_enabled=request.verification_enabled,
        verification_agent=request.verification_agent,
        verification_model=request.verification_model,
        verification_prompt=request.verification_prompt,
    )

    return ExtractionPromptConfig(
        prompt_type=result["prompt_type"],
        prompt_text=result["prompt_text"],
        primary_agent=result["primary_agent"],
        primary_model=result["primary_model"],
        verification_enabled=result["verification_enabled"],
        verification_agent=result.get("verification_agent"),
        verification_model=result.get("verification_model"),
        verification_prompt=result.get("verification_prompt"),
        is_default=False,
        created_at=result.get("created_at").isoformat() if result.get("created_at") else None,
        updated_at=result.get("updated_at").isoformat() if result.get("updated_at") else None,
    )


@router.delete(
    "/projects/{project_id}/roundtable/extraction-prompts/{prompt_type}",
)
async def delete_extraction_prompt(project_id: str, prompt_type: str) -> dict:
    """Delete a custom extraction prompt (revert to default).

    Valid prompt types: feature_extraction, vision_extraction, goals_extraction
    """
    valid_types = ["feature_extraction", "vision_extraction", "goals_extraction"]
    if prompt_type not in valid_types:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid prompt type. Must be one of: {', '.join(valid_types)}",
        )

    deleted = extraction_prompts_storage.delete_extraction_prompt(project_id, prompt_type)
    if not deleted:
        # Not an error - just means they were already using default
        return {"reverted_to_default": True, "prompt_type": prompt_type}

    return {"deleted": True, "reverted_to_default": True, "prompt_type": prompt_type}


# ============================================================================
# SSE Streaming Endpoint
# ============================================================================


def _sse_event(event_type: str, data: dict[str, Any]) -> str:
    """Format an SSE event.

    Args:
        event_type: Event type (user_message, agent_start, agent_chunk, agent_complete, done, error)
        data: Event data dict

    Returns:
        Formatted SSE event string
    """
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


@router.post(
    "/projects/{project_id}/roundtable/sessions/{session_id}/messages/stream",
)
async def stream_message(
    project_id: str,
    session_id: str,
    request_body: MessageRequest,
    request: Request,
) -> StreamingResponse:
    """Send a message and stream agent responses via Server-Sent Events.

    Events emitted:
    - user_message: Confirms user message was received
    - agent_start: Agent is about to respond (includes agent name)
    - agent_complete: Agent response complete (includes full content)
    - done: All agents have responded
    - error: An error occurred

    Args:
        project_id: Project ID
        session_id: Session ID
        request_body: Message request with message and target
        request: FastAPI request (for disconnect detection)

    Returns:
        StreamingResponse with text/event-stream content type
    """
    service = get_roundtable_service()

    # Get or recreate session
    session = service.get_session(session_id)
    if not session:
        session = _restore_session_from_db(service, session_id, project_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

    async def event_generator() -> AsyncGenerator[str, None]:
        """Generate SSE events for roundtable messages."""

        # Set the session_id context for permission callbacks
        current_session_id.set(session_id)

        logger.info("sse_roundtable_stream_started", extra={"session_id": session_id})

        try:
            # First, add user message to session and emit confirmation

            from ..services.roundtable import RoundtableMessage

            user_msg = RoundtableMessage.create("user", request_body.message)
            session.add_message(user_msg)

            yield _sse_event(
                "user_message",
                {
                    "id": user_msg.id,
                    "content": request_body.message,
                    "timestamp": user_msg.timestamp.isoformat(),
                },
            )

            responses = []
            agents_to_query = []
            if request_body.target in ("claude", "both"):
                agents_to_query.append("claude")
            if request_body.target in ("gemini", "both"):
                agents_to_query.append("gemini")

            context = session.get_context()

            for agent_type in agents_to_query:
                # Check for client disconnect
                if await request.is_disconnected():
                    logger.info("sse_client_disconnected", extra={"session_id": session_id})
                    break

                # Emit agent start
                yield _sse_event("agent_start", {"agent": agent_type})

                try:
                    # Send keepalive ping while waiting for agent
                    # Run agent call in background, send pings every 10 seconds
                    import functools

                    loop = asyncio.get_event_loop()

                    # Use functools.partial to pass session as kwarg
                    agent_func = functools.partial(
                        service._send_to_agent,
                        agent_type,
                        request_body.message,
                        context,
                        session=session,
                    )
                    agent_task = loop.run_in_executor(None, agent_func)

                    # Track which permissions we've already emitted events for
                    emitted_permissions: set[str] = set()

                    # Send keepalive pings and check for permission requests while waiting
                    while True:
                        try:
                            llm_response = await asyncio.wait_for(
                                asyncio.shield(agent_task), timeout=1.0
                            )
                            break  # Got response
                        except TimeoutError:
                            # Check for pending permissions for this session
                            pending = permission_manager.get_session_pending(session_id)
                            for perm in pending:
                                if perm.id not in emitted_permissions:
                                    # Emit permission_request SSE event
                                    yield _sse_event(
                                        "permission_request",
                                        {
                                            "permission_id": perm.id,
                                            "tool_name": perm.tool_name,
                                            "params": perm.tool_args,
                                            "preview": _get_preview(perm.tool_name, perm.tool_args),
                                            "agent": agent_type,
                                        },
                                    )
                                    emitted_permissions.add(perm.id)
                                    logger.info(
                                        "sse_permission_request_emitted",
                                        extra={
                                            "session_id": session_id,
                                            "permission_id": perm.id,
                                            "tool_name": perm.tool_name,
                                        },
                                    )

                            # Send keepalive every 10 iterations (10 seconds)
                            if len(emitted_permissions) == 0:
                                # Only send keepalive if no permissions pending
                                # (permission dialog shows its own activity)
                                yield _sse_event("keepalive", {"agent": agent_type})

                            if await request.is_disconnected():
                                logger.info(
                                    "sse_client_disconnected_during_agent",
                                    extra={"session_id": session_id, "agent": agent_type},
                                )
                                # Auto-deny any pending permissions for this session
                                denied_count = permission_manager.deny_session_pending(session_id)
                                if denied_count > 0:
                                    logger.info(
                                        "sse_permissions_auto_denied_on_disconnect",
                                        extra={"session_id": session_id, "count": denied_count},
                                    )
                                return

                    # Create and store the message
                    msg = RoundtableMessage.create(
                        agent_type,  # type: ignore
                        llm_response.content,
                        tokens_used=llm_response.usage.get("total_tokens", 0),
                        model=llm_response.model,
                    )
                    session.add_message(msg)
                    responses.append(msg)

                    # Update context for next agent
                    context = session.get_context()

                    # Emit agent complete with full response
                    yield _sse_event(
                        "agent_complete",
                        {
                            "id": msg.id,
                            "agent": msg.agent,
                            "content": msg.content,
                            "timestamp": msg.timestamp.isoformat(),
                            "tokens_used": msg.tokens_used,
                            "model": msg.model,
                        },
                    )

                except Exception as agent_error:
                    logger.error(
                        "sse_agent_error",
                        extra={
                            "session_id": session_id,
                            "agent": agent_type,
                            "error": str(agent_error),
                        },
                    )
                    # Create error message for this agent
                    error_msg = RoundtableMessage.create(
                        agent_type,  # type: ignore
                        f"[Error: {agent_error!s}]",
                    )
                    session.add_message(error_msg)
                    responses.append(error_msg)

                    yield _sse_event(
                        "agent_complete",
                        {
                            "id": error_msg.id,
                            "agent": error_msg.agent,
                            "content": error_msg.content,
                            "timestamp": error_msg.timestamp.isoformat(),
                            "tokens_used": 0,
                            "model": None,
                        },
                    )
                    # Continue to next agent even if this one failed

            # Persist to database
            messages_data = [
                {
                    "id": m.id,
                    "agent": m.agent,
                    "content": m.content,
                    "timestamp": m.timestamp.isoformat(),
                    "tokens_used": m.tokens_used,
                    "model": m.model,
                }
                for m in session.messages
            ]
            roundtable_storage.save_session(
                session_id=session_id,
                project_id=project_id,
                mode=session.mode,
                messages=messages_data,
                generated_features=None,
            )

            # Emit done event
            yield _sse_event(
                "done",
                {
                    "session_id": session_id,
                    "response_count": len(responses),
                },
            )
            logger.info(
                "sse_roundtable_stream_completed",
                extra={"session_id": session_id, "response_count": len(responses)},
            )

        except Exception as e:
            logger.error(
                "sse_roundtable_stream_error",
                extra={"session_id": session_id, "error": str(e)},
            )
            yield _sse_event("error", {"message": str(e)})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


# ============================================================================
# TDD Spec Extraction & Acceptance
# ============================================================================


class GenerateSpecRequest(BaseModel):
    """Request to generate a TDD spec from conversation."""

    agent_type: str = "gemini"  # Which agent to use for extraction


class GenerateSpecResponse(BaseModel):
    """Response from spec generation."""

    session_id: str
    spec: dict[str, Any]
    components_count: int
    capabilities_count: int
    tests_count: int


class AcceptSpecRequest(BaseModel):
    """Request to accept a generated spec."""

    accepted_by: str = "user"  # Who accepted (user or agent name)


class AcceptSpecResponse(BaseModel):
    """Response from spec acceptance."""

    spec_id: str
    components_created: int
    capabilities_created: int
    tests_created: int


class GetSpecResponse(BaseModel):
    """Response for getting a session's generated spec."""

    session_id: str
    spec: dict[str, Any] | None


@router.post(
    "/projects/{project_id}/roundtable/sessions/{session_id}/generate-spec",
    response_model=GenerateSpecResponse,
)
async def generate_spec(
    project_id: str,
    session_id: str,
    request: GenerateSpecRequest,
):
    """Generate a TDD spec from the roundtable conversation.

    This extracts components, capabilities, and tests from the conversation
    and stores them in the session's generated_spec field for review.

    The spec is ephemeral until accepted - it can be regenerated multiple times
    as the conversation continues and requirements are refined.
    """
    service = get_roundtable_service()

    # Restore session from DB
    session = _restore_session_from_db(service, session_id, project_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Extract spec
    spec = service.extract_spec_from_conversation(session, request.agent_type)

    # Count entities
    components_count = len(spec.get("components", []))
    capabilities_count = sum(len(c.get("capabilities", [])) for c in spec.get("components", []))
    tests_count = sum(
        len(cap.get("tests", []))
        for c in spec.get("components", [])
        for cap in c.get("capabilities", [])
    )

    return GenerateSpecResponse(
        session_id=session_id,
        spec=spec,
        components_count=components_count,
        capabilities_count=capabilities_count,
        tests_count=tests_count,
    )


@router.get(
    "/projects/{project_id}/roundtable/sessions/{session_id}/spec",
    response_model=GetSpecResponse,
)
async def get_spec(
    project_id: str,
    session_id: str,
):
    """Get the generated spec for a session.

    Returns the ephemeral spec that has been generated from the conversation.
    Returns null if no spec has been generated yet.
    """
    spec = roundtable_storage.get_generated_spec(session_id)
    return GetSpecResponse(session_id=session_id, spec=spec)


@router.post(
    "/projects/{project_id}/roundtable/sessions/{session_id}/accept-spec",
    response_model=AcceptSpecResponse,
)
async def accept_spec(
    project_id: str,
    session_id: str,
    request: AcceptSpecRequest,
):
    """Accept the generated spec and create permanent entities.

    This converts the ephemeral generated_spec into permanent:
    - accepted_specs record (permanent spec record)
    - tdd_components
    - tdd_capabilities
    - tdd_tests (with test_capability_links)

    After acceptance, the generated_spec is cleared from the session.
    """
    service = get_roundtable_service()

    try:
        result = service.accept_spec(
            project_id=project_id,
            session_id=session_id,
            accepted_by=request.accepted_by,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return AcceptSpecResponse(
        spec_id=result["spec_id"],
        components_created=result["components_created"],
        capabilities_created=result["capabilities_created"],
        tests_created=result["tests_created"],
    )
