"""Hooks API - Endpoints for external tool integrations.

Provides endpoints for Claude Code hooks and other CLI integrations
to capture tool executions for observation extraction.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from ..services.memory import ObservationQueue
from ..storage import notifications as notif_storage
from ..storage.connection import get_connection

router = APIRouter()
logger = logging.getLogger(__name__)

# ============================================================================
# Tool Filtering - Skip trivial tools that have no learning value
# ============================================================================

# Tools to skip entirely - read-only exploration tools
SKIP_TOOLS: set[str] = {"Read", "Grep", "Glob", "TaskOutput", "WebSearch", "WebFetch"}

# Bash patterns to skip - read-only commands with no learning value
SKIP_BASH_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^git\s+(status|log|diff|show|branch)", re.IGNORECASE),
    re.compile(r"^ls\b", re.IGNORECASE),
    re.compile(r"^cat\b", re.IGNORECASE),
    re.compile(r"^head\b", re.IGNORECASE),
    re.compile(r"^tail\b", re.IGNORECASE),
    re.compile(r"^echo\b", re.IGNORECASE),
    re.compile(r"^pwd\b", re.IGNORECASE),
    re.compile(r"^which\b", re.IGNORECASE),
    re.compile(r"^type\b", re.IGNORECASE),
    re.compile(r"^file\b", re.IGNORECASE),
    re.compile(r"^wc\b", re.IGNORECASE),
]

# Bash patterns to ALWAYS queue - mutating commands worth learning from
ALWAYS_QUEUE_BASH_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^git\s+(commit|push|pull|merge|rebase)", re.IGNORECASE),
    re.compile(r"^npm\s+(install|run|build)", re.IGNORECASE),
    re.compile(r"^pytest\b", re.IGNORECASE),
    re.compile(r"^python.*pytest", re.IGNORECASE),
    re.compile(r"^pip\s+install", re.IGNORECASE),
    re.compile(r"^make\b", re.IGNORECASE),
]

# Error patterns that indicate learning value (always queue these)
ERROR_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\berror\b", re.IGNORECASE),
    re.compile(r"\bexception\b", re.IGNORECASE),
    re.compile(r"\bfailed\b", re.IGNORECASE),
    re.compile(r"\btraceback\b", re.IGNORECASE),
    re.compile(r"\bpanic\b", re.IGNORECASE),
    re.compile(r"\bsegfault\b", re.IGNORECASE),
]

# Minimum output length to consider queueing (very short outputs usually trivial)
MIN_OUTPUT_LENGTH = 200


def should_queue_observation(
    tool_name: str, tool_input: dict[str, Any] | None, tool_output: str | None
) -> tuple[bool, str]:
    """Determine if a tool execution should be queued for observation extraction.

    Returns:
        Tuple of (should_queue, reason) where reason explains the decision.
    """
    output = tool_output or ""

    # Check for errors in output - always queue errors for learning
    for pattern in ERROR_PATTERNS:
        if pattern.search(output):
            return True, "error_detected"

    # Skip tools in the skip list
    if tool_name in SKIP_TOOLS:
        return False, f"skip_tool:{tool_name}"

    # Handle Bash specially - check command patterns
    if tool_name == "Bash":
        command = ""
        if tool_input:
            command = tool_input.get("command", "") or ""

        # Always queue important bash commands
        for pattern in ALWAYS_QUEUE_BASH_PATTERNS:
            if pattern.match(command):
                return True, "important_bash_command"

        # Skip trivial bash commands
        for pattern in SKIP_BASH_PATTERNS:
            if pattern.match(command):
                return False, "skip_bash_pattern"

    # Skip tiny outputs (usually trivial operations)
    if len(output) < MIN_OUTPUT_LENGTH:
        return False, "tiny_output"

    # Default: queue for extraction
    return True, "default_queue"


# Track recently alerted unknown projects to avoid notification spam
# Format: {project_id: last_alert_time}
_unknown_project_alerts: dict[str, datetime] = {}
_ALERT_COOLDOWN = timedelta(minutes=30)  # Only alert once per 30 min per project


def _ensure_project_exists(project_id: str) -> bool:
    """Check if project exists (no auto-creation).

    Previously auto-created projects but this caused junk projects.
    Now only returns True if project already exists.

    Returns:
        True if project exists, False otherwise.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM projects WHERE id = %s", (project_id,))
        return cur.fetchone() is not None


class ToolUseRequest(BaseModel):
    """Request model for tool use hook."""

    project_id: str
    session_id: str
    tool_name: str
    tool_input: dict[str, Any] | None = None
    tool_output: str | None = None


class HookResponse(BaseModel):
    """Response model for hook endpoints."""

    status: str  # "queued", "skipped", "error"
    queued: bool  # Backwards compatibility
    queue_item_id: str
    skip_reason: str | None = None


@router.post("/hooks/tool-use", response_model=HookResponse, status_code=202)
async def hook_tool_use(request: ToolUseRequest) -> HookResponse:
    """Handle tool use hook from Claude Code or other CLI tools.

    Enqueues tool execution for async observation extraction.
    Returns 202 Accepted immediately for fire-and-forget behavior.

    Filters:
    1. Unknown projects - skipped to prevent junk data
    2. Trivial tools (Read, Grep, etc.) - no learning value
    3. Read-only bash commands (ls, cat, etc.) - no learning value
    4. Tiny outputs (<200 chars) - usually trivial

    Always queued:
    - Errors in output (valuable for learning)
    - Mutating bash commands (git commit, npm install, pytest, etc.)
    - Write, Edit, and other mutating tools

    This endpoint is called by PostToolUse hooks installed in
    ~/.claude/hooks/ or similar CLI hook directories.
    """
    # Skip if project doesn't exist (no auto-creation)
    if not _ensure_project_exists(request.project_id):
        # Create notification if not recently alerted (rate-limited)
        now = datetime.now(UTC)
        last_alert = _unknown_project_alerts.get(request.project_id)

        if last_alert is None or (now - last_alert) > _ALERT_COOLDOWN:
            _unknown_project_alerts[request.project_id] = now
            logger.warning(
                f"Hook received for unknown project: {request.project_id} "
                f"(session={request.session_id[:8]}..., tool={request.tool_name})"
            )
            # Create notification in summitflow project for visibility
            try:
                notif_storage.create_notification(
                    project_id="summitflow",
                    notification_type="system",
                    title=f"Unknown project: {request.project_id}",
                    message=(
                        f"Hook received tool execution for unregistered project '{request.project_id}'. "
                        f"Register this project in SummitFlow or check your hook configuration."
                    ),
                    severity="warning",
                    metadata={
                        "unknown_project_id": request.project_id,
                        "tool_name": request.tool_name,
                        "session_id": request.session_id,
                    },
                )
            except Exception as e:
                logger.error(f"Failed to create notification for unknown project: {e}")

        return HookResponse(
            status="skipped",
            queued=False,
            queue_item_id="skipped-unknown-project",
            skip_reason="unknown_project",
        )

    # Apply tool filtering - skip trivial tools to reduce token cost
    should_queue, reason = should_queue_observation(
        tool_name=request.tool_name,
        tool_input=request.tool_input,
        tool_output=request.tool_output,
    )

    if not should_queue:
        logger.info(f"observation_skipped: tool={request.tool_name}, reason={reason}")
        return HookResponse(
            status="skipped",
            queued=False,
            queue_item_id="skipped-filtered",
            skip_reason=reason,
        )

    # Queue for extraction
    queue = ObservationQueue()

    item = await queue.enqueue(
        project_id=request.project_id,
        session_id=request.session_id,
        agent_type="claude-code",  # CLI hooks are from Claude Code
        tool_name=request.tool_name,
        tool_input=request.tool_input,
        tool_output=request.tool_output,
    )

    logger.debug(f"observation_queued: tool={request.tool_name}, id={item['id']}")
    return HookResponse(
        status="queued",
        queued=True,
        queue_item_id=item["id"],
    )
