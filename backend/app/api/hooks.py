"""Hooks API - Endpoints for external tool integrations.

Provides endpoints for Claude Code hooks and other CLI integrations
to capture tool executions for observation extraction.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import UTC, datetime, timedelta
from typing import Any

import redis
from fastapi import APIRouter
from pydantic import BaseModel

from ..services.memory import ObservationQueue
from ..storage import notifications as notif_storage
from ..storage.agent_configs import get_memory_config
from ..storage.connection import get_connection

router = APIRouter()
logger = logging.getLogger(__name__)

# Redis for filtering metrics
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
METRICS_KEY_PREFIX = "obs_filter_metrics"
METRICS_TTL = 86400 * 7  # 7 days


def _get_metrics_redis() -> redis.Redis | None:
    """Get Redis connection for metrics tracking."""
    try:
        r = redis.from_url(REDIS_URL, decode_responses=True, socket_timeout=1)
        r.ping()
        return r
    except redis.RedisError as e:
        logger.warning(f"Redis unavailable for metrics: {e}")
        return None


def _increment_metric(metric: str, skip_reason: str | None = None) -> None:
    """Increment a filtering metric in Redis.

    Metrics tracked:
    - tools_received: Total tools received
    - tools_queued: Tools that passed filter and were queued
    - tools_skipped: Tools that were skipped by filter
    - skip_reasons:{reason}: Breakdown by skip reason
    """
    r = _get_metrics_redis()
    if r is None:
        return

    try:
        pipe = r.pipeline()
        # Increment total count
        pipe.incr(f"{METRICS_KEY_PREFIX}:{metric}")
        pipe.expire(f"{METRICS_KEY_PREFIX}:{metric}", METRICS_TTL)

        # Track skip reason breakdown
        if skip_reason:
            pipe.hincrby(f"{METRICS_KEY_PREFIX}:skip_reasons", skip_reason, 1)
            pipe.expire(f"{METRICS_KEY_PREFIX}:skip_reasons", METRICS_TTL)

        pipe.execute()
    except redis.RedisError as e:
        logger.warning(f"Failed to increment metric: {e}")


def get_filtering_metrics() -> dict[str, Any]:
    """Get filtering metrics from Redis.

    Returns:
        Dict with tools_received, tools_queued, tools_skipped, skip_reasons, filter_effectiveness
    """
    r = _get_metrics_redis()
    if r is None:
        return {
            "tools_received": 0,
            "tools_queued": 0,
            "tools_skipped": 0,
            "skip_reasons": {},
            "filter_effectiveness": 0.0,
        }

    try:
        pipe = r.pipeline()
        pipe.get(f"{METRICS_KEY_PREFIX}:tools_received")
        pipe.get(f"{METRICS_KEY_PREFIX}:tools_queued")
        pipe.get(f"{METRICS_KEY_PREFIX}:tools_skipped")
        pipe.hgetall(f"{METRICS_KEY_PREFIX}:skip_reasons")
        results = pipe.execute()

        received = int(results[0] or 0)
        queued = int(results[1] or 0)
        skipped = int(results[2] or 0)
        skip_reasons = {k: int(v) for k, v in (results[3] or {}).items()}

        # Calculate filter effectiveness (% of tools filtered)
        effectiveness = (skipped / received * 100) if received > 0 else 0.0

        return {
            "tools_received": received,
            "tools_queued": queued,
            "tools_skipped": skipped,
            "skip_reasons": skip_reasons,
            "filter_effectiveness": round(effectiveness, 1),
        }
    except redis.RedisError as e:
        logger.warning(f"Failed to get metrics: {e}")
        return {
            "tools_received": 0,
            "tools_queued": 0,
            "tools_skipped": 0,
            "skip_reasons": {},
            "filter_effectiveness": 0.0,
        }


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
    skip_memory: bool = False  # Session-level flag to bypass memory capture


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
    # Track all tools received
    _increment_metric("tools_received")

    # Session-level skip flag (for debugging/verification sessions)
    if request.skip_memory:
        logger.debug("observation_skipped: session skip_memory flag set")
        _increment_metric("tools_skipped", "session_skip_flag")
        return HookResponse(
            status="skipped",
            queued=False,
            queue_item_id="skipped-session-flag",
            skip_reason="session_skip_flag",
        )

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

        _increment_metric("tools_skipped", "unknown_project")
        return HookResponse(
            status="skipped",
            queued=False,
            queue_item_id="skipped-unknown-project",
            skip_reason="unknown_project",
        )

    # Project-level memory check
    memory_config = get_memory_config(request.project_id)
    if not memory_config.get("memory_enabled", True):
        logger.debug(f"observation_skipped: memory disabled for project {request.project_id}")
        _increment_metric("tools_skipped", "memory_disabled")
        return HookResponse(
            status="skipped",
            queued=False,
            queue_item_id="skipped-memory-disabled",
            skip_reason="memory_disabled",
        )

    if not memory_config.get("observations_enabled", True):
        logger.debug(f"observation_skipped: observations disabled for project {request.project_id}")
        _increment_metric("tools_skipped", "observations_disabled")
        return HookResponse(
            status="skipped",
            queued=False,
            queue_item_id="skipped-observations-disabled",
            skip_reason="observations_disabled",
        )

    # Apply tool filtering - skip trivial tools to reduce token cost
    should_queue, reason = should_queue_observation(
        tool_name=request.tool_name,
        tool_input=request.tool_input,
        tool_output=request.tool_output,
    )

    if not should_queue:
        logger.info(f"observation_skipped: tool={request.tool_name}, reason={reason}")
        _increment_metric("tools_skipped", reason)
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

    # Handle case where memory was disabled at storage layer
    if item is None:
        logger.debug("observation_skipped: memory disabled at storage layer")
        _increment_metric("tools_skipped", "storage_memory_disabled")
        return HookResponse(
            status="skipped",
            queued=False,
            queue_item_id="skipped-storage-disabled",
            skip_reason="storage_memory_disabled",
        )

    logger.debug(f"observation_queued: tool={request.tool_name}, id={item['id']}")
    _increment_metric("tools_queued")
    return HookResponse(
        status="queued",
        queued=True,
        queue_item_id=item["id"],
    )
