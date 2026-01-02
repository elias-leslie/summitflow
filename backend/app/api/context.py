"""Context API - Progressive disclosure endpoints for token-efficient context loading.

This module provides REST API endpoints for the context system:
- GET /projects/{project_id}/context/index - Get compact context index (~500 tokens)
- POST /projects/{project_id}/context/expand - Expand specific entity for full content
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..services.context_helpers import (
    filter_rules_by_files,
    get_observations_for_files,
    get_patterns_for_files,
)
from ..services.memory import ContextBuilder
from ..storage.agent_configs import is_memory_feature_enabled

logger = logging.getLogger(__name__)


def format_relative_time(timestamp: str | None) -> str:
    """Format timestamp as a human-readable relative time.

    Args:
        timestamp: ISO 8601 timestamp string (e.g., "2024-12-24T09:28:00")

    Returns:
        Human-readable relative time:
        - "9:28 AM today" for today
        - "yesterday 3:00 PM" for yesterday
        - "Monday 3:00 PM" for this week (last 7 days)
        - "Dec 22" for older dates
    """
    if not timestamp:
        return ""

    try:
        # Parse ISO timestamp (handles both with and without timezone)
        if timestamp.endswith("Z"):
            timestamp = timestamp[:-1] + "+00:00"
        dt = datetime.fromisoformat(timestamp)

        # Convert to local timezone for display
        local_tz = ZoneInfo("America/Los_Angeles")  # PST/PDT
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("UTC"))
        dt_local = dt.astimezone(local_tz)

        now = datetime.now(local_tz)
        today = now.date()
        yesterday = today - timedelta(days=1)
        dt_date = dt_local.date()

        time_str = dt_local.strftime("%-I:%M %p").lstrip("0")

        if dt_date == today:
            return f"{time_str} today"
        elif dt_date == yesterday:
            return f"yesterday {time_str}"
        elif (today - dt_date).days < 7:
            day_name = dt_local.strftime("%A")
            return f"{day_name} {time_str}"
        else:
            return dt_local.strftime("%b %-d")
    except (ValueError, TypeError):
        return ""


def format_session_context(
    git: dict[str, Any] | None,
    diary: list[dict[str, Any]],
    observations: list[dict[str, Any]],
) -> str:
    """Format session context as plain text for injection.

    Args:
        git: Git state dict with current_time, recent_files, uncommitted_count
        diary: List of diary entries with full content
        observations: List of observations with full content

    Returns:
        Formatted plain text context block. No truncation.
    """
    lines = ["## Recent Project Context"]

    # Current time from git state
    if git and git.get("current_time"):
        lines.append(f"Current time: {git['current_time']}")
        lines.append("")

    # Git section
    if git:
        lines.append("**Git:**")
        if git.get("recent_files"):
            files = git["recent_files"]
            if isinstance(files, str):
                files = files.split(",")
            lines.append(f"- Last modified: {', '.join(f.strip() for f in files[:5])}")
        if git.get("uncommitted_count") is not None:
            lines.append(f"- Uncommitted: {git['uncommitted_count']} files")
        lines.append("")

    # Tools hint (zero-cost progressive disclosure)
    lines.append("**Tools:** `member-dis search|expand|index` | `st ready|update|close`")
    lines.append("")

    # Recent sessions (diary entries)
    if diary:
        lines.append("**Recent Sessions:**")
        lines.append("")
        for entry in diary:
            session_id = entry.get("session_id", "unknown")[:8]
            outcome = entry.get("outcome", "unknown")
            timestamp = format_relative_time(entry.get("created_at"))

            outcome_label = {"success": "Success", "failure": "Failure"}.get(
                outcome, outcome.title() if outcome else "Partial"
            )

            lines.append(f"Session {session_id} ({outcome_label}) - {timestamp}:")

            # What worked
            what_worked = entry.get("what_worked") or []
            if isinstance(what_worked, str):
                import json

                try:
                    what_worked = json.loads(what_worked)
                except (json.JSONDecodeError, TypeError):
                    what_worked = []
            for item in what_worked:
                lines.append(f"  ✓ {item}")

            # What failed
            what_failed = entry.get("what_failed") or []
            if isinstance(what_failed, str):
                import json

                try:
                    what_failed = json.loads(what_failed)
                except (json.JSONDecodeError, TypeError):
                    what_failed = []
            for item in what_failed:
                lines.append(f"  ✗ {item}")

            lines.append("")

    # Recent observations
    if observations:
        lines.append("**Recent Observations:**")
        for obs in observations:
            obs_type = obs.get("observation_type", "general")
            timestamp = format_relative_time(obs.get("created_at"))
            title = obs.get("title", "No title")

            lines.append(f"- [{obs_type}] {timestamp} - {title}")

            # Full narrative
            narrative = obs.get("narrative")
            if narrative:
                lines.append(f"  {narrative}")

            # Files modified
            files_modified = obs.get("files_modified") or []
            if files_modified:
                files_str = ", ".join(files_modified[:5])
                lines.append(f"  → Files: {files_str}")

            lines.append("")

    lines.append("Use /projects/{project_id}/context/expand for full details.")

    return "\n".join(lines)


router = APIRouter()


class ExpandRequest(BaseModel):
    """Request model for entity expansion."""

    entity_id: str  # Format: "type:uuid" (e.g., "obs:abc-123")
    session_id: str | None = None  # Optional session ID for access logging
    task_id: str | None = None  # Optional task ID for correlation


class ExpandResponse(BaseModel):
    """Response model for entity expansion."""

    entity_id: str
    type: str
    content: dict[str, Any]
    token_count: int
    jsonl: str | None = None  # Compact JSON-lines format for patterns


class ContextIndexResponse(BaseModel):
    """Response model for context index."""

    project_id: str
    session_id: str | None
    items: list[dict[str, Any]]
    item_count: int
    index_tokens: int
    full_tokens: int
    reduction_pct: float
    from_cache: bool = False
    instructions: str


@router.get("/{project_id}/context/index", response_model=ContextIndexResponse)
async def get_context_index(
    project_id: str,
    session_id: str | None = Query(None, description="Filter by session ID"),
    limit: int = Query(20, ge=1, le=50, description="Max items per category"),
    include_observations: bool = Query(True, description="Include observations"),
    include_checkpoints: bool = Query(True, description="Include checkpoints"),
    include_patterns: bool = Query(True, description="Include applied patterns"),
) -> ContextIndexResponse:
    """Get a compact context index (~500 tokens target).

    Returns a summary of available context. Each item includes:
    - id: Entity ID for expand_entity()
    - type: Entity type (observation, checkpoint, pattern)
    - title/summary: Brief description
    - token_estimate: Tokens if expanded

    Use this to decide what context to load, then call /expand for full content.
    """
    builder = ContextBuilder(project_id=project_id, session_id=session_id)

    index = builder.build_index(
        limit=limit,
        include_observations=include_observations,
        include_checkpoints=include_checkpoints,
        include_patterns=include_patterns,
    )

    return ContextIndexResponse(**index)


@router.post("/{project_id}/context/expand", response_model=ExpandResponse)
async def expand_entity(
    project_id: str,
    request: ExpandRequest,
) -> ExpandResponse:
    """Expand an entity from the context index to get full content.

    Accepts entity_id in format "type:uuid":
    - obs:abc-123 - Observation
    - cp:xyz-456 - Checkpoint
    - pat:def-789 - Pattern

    Returns the full content and token count for the entity.
    For patterns, this also increments the usage_count.

    Optional: Pass session_id and task_id for access logging and correlation.
    """
    builder = ContextBuilder(
        project_id=project_id,
        session_id=request.session_id,
        access_source="api",
        task_id=request.task_id,
    )

    try:
        result = builder.expand_entity(request.entity_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    return ExpandResponse(**result)


class SessionStartRequest(BaseModel):
    """Request model for session-start context injection.

    All fields optional for backward compatibility.
    """

    current_time: str | None = None  # Client's current time, e.g. "2024-12-24 09:45 PST"
    recent_files: str | None = None  # Comma-separated list of recently modified files
    uncommitted_count: int | None = None  # Number of uncommitted changes
    session_id: str | None = None  # Optional session ID for access tracking


class SessionStartContextResponse(BaseModel):
    """Response model for session-start context injection."""

    context_block: str
    token_estimate: int
    items_included: int
    patterns_index: list[dict[str, Any]] = Field(default_factory=list)
    tools_hint: str = "`member-dis search|expand|index` | `st ready|update|close`"


@router.post("/{project_id}/context/session-start", response_model=SessionStartContextResponse)
async def get_session_start_context(
    project_id: str,
    request: SessionStartRequest | None = None,
) -> SessionStartContextResponse:
    """Get context for automatic session-start injection.

    Called by SessionStart hook to inject recent context at the start
    of new Claude Code sessions. Returns empty block if context injection
    is disabled for the project.

    Returns:
        context_block: Plain text formatted for injection
        token_estimate: Estimated tokens in the block
        items_included: Number of items included
    """
    import time

    from ..storage.memory import (
        count_diary_entries_since,
        count_observations_since,
        list_diary_entries,
        list_observations,
    )

    # Run quick health check (auto-applies approved patterns)
    # Target: <100ms impact
    try:
        from ..services.memory.health_checker import MemoryHealthChecker

        health_start = time.time()
        checker = MemoryHealthChecker(project_id)
        checker.quick_check()
        health_elapsed = (time.time() - health_start) * 1000
        if health_elapsed > 100:
            logger.warning(
                f"Session-start health check took {health_elapsed:.1f}ms (target: <100ms)"
            )
    except Exception as e:
        logger.warning(f"Session-start health check failed: {e}")

    # Check if context injection is enabled for this project
    if not is_memory_feature_enabled(project_id, "context_injection"):
        return SessionStartContextResponse(
            context_block="",
            token_estimate=0,
            items_included=0,
        )

    # Calculate adaptive limits based on recent activity
    # Diary: 3-5 entries based on sessions in last 24h
    diary_count = count_diary_entries_since(project_id, hours=24)
    diary_limit = min(5, max(3, diary_count))

    # Observations: 4-8 based on observations in last 2h
    obs_count = count_observations_since(project_id, hours=2)
    obs_limit = min(8, max(4, obs_count))

    # Fetch data
    diary = list_diary_entries(project_id=project_id, limit=diary_limit)
    observations = list_observations(
        project_id=project_id,
        min_confidence=0.7,
        limit=obs_limit,
    )

    # Build git state from request
    git_state: dict[str, Any] | None = None
    if request:
        git_state = {}
        if request.current_time:
            git_state["current_time"] = request.current_time
        if request.recent_files:
            git_state["recent_files"] = request.recent_files
        if request.uncommitted_count is not None:
            git_state["uncommitted_count"] = request.uncommitted_count

    # Build pattern index (compact list of applied patterns)
    from ..services.memory.pattern_service import PatternService
    from ..storage.memory import increment_pattern_usage

    pattern_service = PatternService(project_id)
    applied_patterns = pattern_service.list_patterns(status="applied", limit=50)
    patterns_index = [
        {
            "id": f"pat:{p['id'][-8:]}",  # Short ID (last 8 chars)
            "title": p["title"][:50],  # Truncate long titles
            "type": p.get("pattern_type", "rule"),
        }
        for p in applied_patterns
    ]

    # Track pattern usage and log access for session-start injection
    session_id = request.session_id if request else None
    if applied_patterns and session_id:
        from ..storage.context_access import log_context_access

        for pattern in applied_patterns:
            pattern_id = str(pattern["id"])
            # Increment usage count
            increment_pattern_usage(pattern_id, session_id=session_id)
            # Log access as injection source
            try:
                log_context_access(
                    project_id=project_id,
                    session_id=session_id,
                    entity_type="pattern",
                    entity_id=pattern_id,
                    access_source="injection",
                )
            except Exception as e:
                logger.warning(f"Failed to log pattern injection access: {e}")

    # Format using new function
    context_block = format_session_context(git_state, diary, observations)

    # Count items included
    items_count = len(diary) + len(observations) + len(patterns_index)

    token_estimate = len(context_block) // 4  # Rough estimate

    return SessionStartContextResponse(
        context_block=context_block,
        token_estimate=token_estimate,
        items_included=items_count,
        patterns_index=patterns_index,
    )


class TimelineResponse(BaseModel):
    """Response model for timeline/context-around endpoint."""

    anchor: dict[str, Any]
    before: list[dict[str, Any]]
    after: list[dict[str, Any]]
    total_tokens: int


@router.get("/{project_id}/context/timeline", response_model=TimelineResponse)
async def get_context_timeline(
    project_id: str,
    anchor_id: str = Query(..., description="Observation ID to center timeline on"),
    before: int = Query(5, ge=0, le=20, description="Number of items before anchor"),
    after: int = Query(5, ge=0, le=20, description="Number of items after anchor"),
) -> TimelineResponse:
    """Get observations around a specific anchor point in time.

    Useful for understanding the context around a particular observation.
    Returns the anchor observation plus observations before and after it.

    Args:
        anchor_id: The observation ID to center the timeline on
        before: Number of observations to fetch before the anchor
        after: Number of observations to fetch after the anchor

    Returns:
        anchor: The anchor observation
        before: Observations before the anchor (descending order)
        after: Observations after the anchor (ascending order)
        total_tokens: Estimated token count for all content
    """
    from ..storage import memory as memory_storage

    # Get the anchor observation
    anchor_obs = memory_storage.get_observation(anchor_id)
    if anchor_obs is None:
        raise HTTPException(status_code=404, detail=f"Observation {anchor_id} not found")

    # Verify project match
    if anchor_obs.get("project_id") != project_id:
        raise HTTPException(status_code=404, detail=f"Observation {anchor_id} not found")

    anchor_time = anchor_obs.get("created_at")
    if not anchor_time:
        raise HTTPException(status_code=400, detail=f"Observation {anchor_id} has no timestamp")

    # Get observations before and after
    from ..storage.memory_embeddings import (
        get_observations_after_time,
        get_observations_before_time,
    )

    before_obs = get_observations_before_time(
        project_id=project_id,
        before_time=anchor_time,
        exclude_id=anchor_id,
        limit=before,
    )

    after_obs = get_observations_after_time(
        project_id=project_id,
        after_time=anchor_time,
        exclude_id=anchor_id,
        limit=after,
    )

    # Calculate token estimate (rough: 4 chars per token)
    def estimate_tokens(obs: dict[str, Any]) -> int:
        content = f"{obs.get('title', '')} {obs.get('narrative', '')}"
        return len(content) // 4

    total_tokens = estimate_tokens(anchor_obs)
    total_tokens += sum(estimate_tokens(o) for o in before_obs)
    total_tokens += sum(estimate_tokens(o) for o in after_obs)

    return TimelineResponse(
        anchor=anchor_obs,
        before=before_obs,
        after=after_obs,
        total_tokens=total_tokens,
    )


class TaskContextResponse(BaseModel):
    """Response model for task context."""

    files: list[str]
    rules: list[str]
    rule_contents: dict[str, str]
    patterns: list[dict[str, Any]]
    observations: list[dict[str, Any]]


# Rules directory (project-level and global)
PROJECT_RULES_DIR = Path("/home/kasadis/summitflow/.claude/rules")
GLOBAL_RULES_DIR = Path("/home/kasadis/.claude/rules")


def _read_rule_file(filename: str) -> str | None:
    """Read a rule file from project or global rules directory."""
    # Try project rules first
    project_path = PROJECT_RULES_DIR / filename
    if project_path.exists():
        return project_path.read_text()

    # Fall back to global rules
    global_path = GLOBAL_RULES_DIR / filename
    if global_path.exists():
        return global_path.read_text()

    return None


@router.get("/{project_id}/context/for-task", response_model=TaskContextResponse)
async def get_context_for_task(
    project_id: str,
    files: str = Query(..., description="Comma-separated list of file paths affected by the task"),
) -> TaskContextResponse:
    """Get context relevant to a specific task based on files it affects.

    Returns:
        - rules: List of relevant rule filenames
        - rule_contents: Dict mapping rule filename to content
        - patterns: List of relevant learned patterns
        - observations: List of relevant observations (errors, decisions)
    """
    # Parse files list
    file_list = [f.strip() for f in files.split(",") if f.strip()]

    if not file_list:
        raise HTTPException(status_code=400, detail="No files provided")

    # Get relevant rules
    rule_names = filter_rules_by_files(file_list)

    # Read rule contents
    rule_contents: dict[str, str] = {}
    for rule in rule_names:
        content = _read_rule_file(rule)
        if content:
            rule_contents[rule] = content

    # Get relevant patterns
    patterns = get_patterns_for_files(project_id, file_list, min_confidence=0.7)

    # Get relevant observations
    observations = get_observations_for_files(
        project_id, file_list, types=["error", "decision"], limit=10
    )

    return TaskContextResponse(
        files=file_list,
        rules=rule_names,
        rule_contents=rule_contents,
        patterns=patterns,
        observations=observations,
    )
