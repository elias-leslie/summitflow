"""Hooks API - Endpoints for external tool integrations.

Provides endpoints for Claude Code hooks and other CLI integrations
to capture tool executions for observation extraction.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from ..services.memory import ObservationQueue

router = APIRouter()


class ToolUseRequest(BaseModel):
    """Request model for tool use hook."""

    project_id: str
    session_id: str
    tool_name: str
    tool_input: dict[str, Any] | None = None
    tool_output: str | None = None


class HookResponse(BaseModel):
    """Response model for hook endpoints."""

    queued: bool
    queue_item_id: str


@router.post("/hooks/tool-use", response_model=HookResponse, status_code=202)
async def hook_tool_use(request: ToolUseRequest) -> HookResponse:
    """Handle tool use hook from Claude Code or other CLI tools.

    Enqueues tool execution for async observation extraction.
    Returns 202 Accepted immediately for fire-and-forget behavior.

    This endpoint is called by PostToolUse hooks installed in
    ~/.claude/hooks/ or similar CLI hook directories.
    """
    queue = ObservationQueue()

    item = await queue.enqueue(
        project_id=request.project_id,
        session_id=request.session_id,
        agent_type="claude-code",  # CLI hooks are from Claude Code
        tool_name=request.tool_name,
        tool_input=request.tool_input,
        tool_output=request.tool_output,
    )

    return HookResponse(queued=True, queue_item_id=item["id"])
