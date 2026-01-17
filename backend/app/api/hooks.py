"""Hooks API - Endpoints for external tool integrations.

Legacy memory system hooks - now returns skipped responses.
Memory functionality moved to Agent Hub with Graphiti knowledge graph.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()
logger = logging.getLogger(__name__)


class ToolUseRequest(BaseModel):
    """Request model for tool use hook."""

    project_id: str
    session_id: str
    tool_name: str
    tool_input: dict[str, Any] | None = None
    tool_output: str | None = None
    skip_memory: bool = False


class HookResponse(BaseModel):
    """Response model for hook endpoints."""

    status: str  # "queued", "skipped", "error"
    queued: bool  # Backwards compatibility
    queue_item_id: str
    skip_reason: str | None = None


@router.post("/hooks/tool-use", response_model=HookResponse, status_code=202)
async def hook_tool_use(request: ToolUseRequest) -> HookResponse:
    """Handle tool use hook from Claude Code or other CLI tools.

    Memory system removed - now returns skipped response.
    Memory functionality moved to Agent Hub with Graphiti knowledge graph.
    """
    return HookResponse(
        status="skipped",
        queued=False,
        queue_item_id="skipped-memory-system-removed",
        skip_reason="memory_system_removed",
    )


class UserPromptSubmitRequest(BaseModel):
    """Request model for user prompt submit hook."""

    project_id: str
    session_id: str
    prompt_number: int
    prompt_text: str


class UserPromptSubmitResponse(BaseModel):
    """Response model for user prompt submit hook."""

    status: str  # "captured", "skipped", "error"
    prompt_id: str | None = None
    skip_reason: str | None = None


@router.post(
    "/hooks/user-prompt-submit",
    response_model=UserPromptSubmitResponse,
    status_code=202,
)
async def hook_user_prompt_submit(
    request: UserPromptSubmitRequest,
) -> UserPromptSubmitResponse:
    """Capture user prompts for semantic search.

    Memory system removed - now returns skipped response.
    Memory functionality moved to Agent Hub with Graphiti knowledge graph.
    """
    return UserPromptSubmitResponse(
        status="skipped",
        skip_reason="memory_system_removed",
    )
