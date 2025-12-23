"""Hooks API - Endpoints for external tool integrations.

Provides endpoints for Claude Code hooks and other CLI integrations
to capture tool executions for observation extraction.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from ..services.memory import ObservationQueue
from ..storage.connection import get_connection

router = APIRouter()


def _ensure_project_exists(project_id: str) -> bool:
    """Ensure project exists, creating it if necessary.

    Auto-creates minimal project entry for unregistered projects
    so observation capture doesn't fail on FK constraint.

    Returns:
        True if project was created, False if it already existed.
    """
    with get_connection() as conn, conn.cursor() as cur:
        # Check if exists
        cur.execute("SELECT id FROM projects WHERE id = %s", (project_id,))
        if cur.fetchone():
            return False

        # Auto-create with sensible defaults
        now = datetime.now(UTC)
        cur.execute(
            """
            INSERT INTO projects (id, name, base_url, health_endpoint, root_path, created_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO NOTHING
            """,
            (
                project_id,
                project_id,  # Use ID as name (can be updated later)
                "http://localhost:8000",  # Placeholder
                "/health",
                None,  # No root_path - can be set later
                now,
            ),
        )
        conn.commit()
        return True


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

    Auto-creates project if it doesn't exist to avoid FK constraint failures.

    This endpoint is called by PostToolUse hooks installed in
    ~/.claude/hooks/ or similar CLI hook directories.
    """
    # Ensure project exists (auto-create if needed)
    _ensure_project_exists(request.project_id)

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
