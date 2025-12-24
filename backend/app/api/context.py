"""Context API - Progressive disclosure endpoints for token-efficient context loading.

This module provides REST API endpoints for the context system:
- GET /projects/{project_id}/context/index - Get compact context index (~500 tokens)
- POST /projects/{project_id}/context/expand - Expand specific entity for full content
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ..services.memory import ContextBuilder
from ..storage.agent_configs import is_memory_feature_enabled


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


class ExpandResponse(BaseModel):
    """Response model for entity expansion."""

    entity_id: str
    type: str
    content: dict[str, Any]
    token_count: int


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
    """
    builder = ContextBuilder(project_id=project_id)

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


class SessionStartContextResponse(BaseModel):
    """Response model for session-start context injection."""

    context_block: str
    token_estimate: int
    items_included: int


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
    # Check if context injection is enabled for this project
    if not is_memory_feature_enabled(project_id, "context_injection"):
        return SessionStartContextResponse(
            context_block="",
            token_estimate=0,
            items_included=0,
        )

    # Default limit; will be updated to adaptive limits in task 2.4
    limit = 10

    builder = ContextBuilder(project_id=project_id)
    index = builder.build_index(
        limit=limit,
        include_observations=True,
        include_checkpoints=True,
        include_patterns=True,
    )

    # Return empty if no items
    if not index.get("items"):
        return SessionStartContextResponse(
            context_block="",
            token_estimate=0,
            items_included=0,
        )

    # Format as plain text for injection
    lines = ["## Recent Project Context", ""]
    for item in index["items"]:
        item_type = item.get("type", "unknown")
        title = item.get("title", item.get("summary", "No title"))
        created = item.get("created_at", "")[:10] if item.get("created_at") else ""

        if item_type == "observation":
            obs_type = item.get("observation_type", "general")
            lines.append(f"- [{obs_type}] {title} ({created})")
        elif item_type == "checkpoint":
            lines.append(f"- [checkpoint] {title} ({created})")
        elif item_type == "pattern":
            lines.append(f"- [pattern] {title}")
        else:
            lines.append(f"- {title}")

    lines.append("")
    lines.append("Use /projects/{project_id}/context/expand for full details.")

    context_block = "\n".join(lines)
    token_estimate = len(context_block) // 4  # Rough estimate

    return SessionStartContextResponse(
        context_block=context_block,
        token_estimate=token_estimate,
        items_included=len(index["items"]),
    )
