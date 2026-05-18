"""Tasks API - Observability endpoints for Agent Hub integration.

Provides endpoints to fetch Agent Hub session events for task execution
observability, including thinking blocks, tool calls, memory events, etc.
"""

from __future__ import annotations

import re
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ...logging_config import get_logger
from ...services._agent_hub_config import (
    AGENT_HUB_URL,
    SUMMITFLOW_CLIENT_ID,
    build_agent_hub_headers,
)
from ...storage.events import get_events_by_trace
from ...storage.tasks.core import add_agent_hub_session, get_agent_hub_sessions
from .helpers import verify_task_project

logger = get_logger(__name__)
router = APIRouter()
_SESSION_STARTED_RE = re.compile(r"Agent session started:\s+([A-Za-z0-9][A-Za-z0-9_-]{2,120})")


# --- Models ---


class AgentHubEvent(BaseModel):
    """Single event from Agent Hub session."""

    id: str
    session_id: str | None = None
    session_index: int = 0
    turn: int
    sequence: int
    event_type: str
    role: str | None = None
    content: str | None = None
    tool_name: str | None = None
    tool_input: dict[str, Any] | None = None
    tool_output: dict[str, Any] | None = None
    tokens: int | None = None
    duration_ms: int | None = None
    model_used: str | None = None
    agent_id: str | None = None
    agent_name: str | None = None
    created_at: str


class AgentHubLiveActivity(BaseModel):
    """Live execution state mirrored from Agent Hub session responses."""

    phase: str
    status: str
    summary: str | None = None
    health: str
    stalled: bool = False
    stall_reason: str | None = None
    quiet_for_seconds: int | None = None
    current_tool_name: str | None = None
    last_tool_name: str | None = None
    last_read_path: str | None = None
    last_write_path: str | None = None
    last_command: str | None = None
    last_validation_command: str | None = None
    last_command_exit_code: int | None = None
    outstanding_tool_calls: int = 0
    tool_calls_count: int = 0
    termination_reason: str | None = None
    files_touched: list[str] = Field(default_factory=list)


class AgentHubSessionSummary(BaseModel):
    """Task-linked Agent Hub session summary."""

    id: str
    status: str
    agent_slug: str | None = None
    requested_model: str | None = None
    effective_model: str | None = None
    requested_provider: str | None = None
    effective_provider: str | None = None
    fallback_used: bool = False
    fallback_reason: str | None = None
    updated_at: str
    live_activity: AgentHubLiveActivity | None = None


class AgentHubEventsResponse(BaseModel):
    """Response containing Agent Hub events for a task."""

    task_id: str
    session_ids: list[str]
    sessions: list[AgentHubSessionSummary]
    events: list[AgentHubEvent]
    total: int
    max_turn: int


# --- Agent Hub HTTP helpers ---

DEFAULT_REQUEST_SOURCE = "summitflow-observability"
HTTP_TIMEOUT = 30.0
EMPTY_SESSION_RESULT: dict[str, Any] = {"events": [], "total": 0, "max_turn": 0}


def _get_client_id() -> str:
    """Get Agent Hub client ID from centralized config."""
    if not SUMMITFLOW_CLIENT_ID:
        raise HTTPException(status_code=500, detail="Missing SUMMITFLOW_CLIENT_ID credential for Agent Hub")
    return SUMMITFLOW_CLIENT_ID


def _build_headers() -> dict[str, str]:
    return build_agent_hub_headers(
        client_id=_get_client_id(),
        default_request_source=DEFAULT_REQUEST_SOURCE,
    )


def _fetch_session_events(
    session_id: str,
    event_type: str | None = None,
    turn: int | None = None,
    page: int = 1,
    page_size: int = 500,
) -> dict[str, Any]:
    """Fetch events from Agent Hub for a single session."""
    params: dict[str, Any] = {"page": page, "page_size": page_size}
    if event_type:
        params["event_type"] = event_type
    if turn is not None:
        params["turn"] = turn
    url = f"{AGENT_HUB_URL}/api/sessions/{session_id}/events"
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            response = client.get(url, headers=_build_headers(), params=params)
        if response.status_code == 404:
            return EMPTY_SESSION_RESULT
        if response.status_code >= 400:
            logger.warning("Agent Hub API error", session_id=session_id, status=response.status_code, detail=response.text[:200])
            return EMPTY_SESSION_RESULT
        return dict(response.json())
    except httpx.ConnectError:
        logger.warning("Cannot connect to Agent Hub", url=AGENT_HUB_URL)
        return EMPTY_SESSION_RESULT
    except Exception as e:
        logger.error("Failed to fetch Agent Hub events", error=str(e))
        return EMPTY_SESSION_RESULT


def _fetch_session_summary(session_id: str) -> dict[str, Any] | None:
    """Fetch a single Agent Hub session summary."""
    url = f"{AGENT_HUB_URL}/api/sessions/{session_id}"
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            response = client.get(url, headers=_build_headers())
        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            logger.warning("Agent Hub session API error", session_id=session_id, status=response.status_code, detail=response.text[:200])
            return None
        return dict(response.json())
    except httpx.ConnectError:
        logger.warning("Cannot connect to Agent Hub", url=AGENT_HUB_URL)
        return None
    except Exception as e:
        logger.error("Failed to fetch Agent Hub session summary", error=str(e))
        return None


def _infer_session_task_id(session: dict[str, Any]) -> str | None:
    external_id = session.get("external_id")
    if isinstance(external_id, str) and external_id.startswith("task-"):
        return external_id
    return None


def _fetch_task_sessions_by_external_id(
    project_id: str,
    task_id: str,
    page_size: int = 100,
) -> list[dict[str, Any]]:
    """Fetch Agent Hub sessions linked to a task by explicit external_id.

    Branch/path inference can attach unrelated operator sessions after a checkout
    switches to a task branch, so only Agent Hub's explicit external_id link is
    used here.
    """
    url = f"{AGENT_HUB_URL}/api/sessions"
    params = {
        "project_id": project_id,
        "external_id": task_id,
        "page": 1,
        "page_size": page_size,
    }
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            response = client.get(url, headers=_build_headers(), params=params)
        if response.status_code >= 400:
            logger.warning("Agent Hub session list API error", task_id=task_id, project_id=project_id, status=response.status_code, detail=response.text[:200])
            return []
        raw_sessions = dict(response.json()).get("sessions", [])
        if not isinstance(raw_sessions, list):
            return []
        sessions = [dict(s) for s in raw_sessions if isinstance(s, dict)]
    except httpx.ConnectError:
        logger.warning("Cannot connect to Agent Hub", url=AGENT_HUB_URL)
        return []
    except Exception as e:
        logger.error("Failed to fetch Agent Hub sessions by external_id", error=str(e))
        return []

    linked: list[dict[str, Any]] = []
    seen: set[str] = set()
    for session in sessions:
        session_id = session.get("id")
        if _infer_session_task_id(session) != task_id or not isinstance(session_id, str) or not session_id:
            continue
        if session_id not in seen:
            seen.add(session_id)
            linked.append(session)
    return linked


def _build_session_summary(session: dict[str, Any]) -> AgentHubSessionSummary:
    """Build a normalized session summary from Agent Hub session JSON."""
    live_activity = session.get("live_activity")
    return AgentHubSessionSummary(
        id=session.get("id", ""),
        status=session.get("status", "unknown"),
        agent_slug=session.get("agent_slug"),
        requested_model=session.get("requested_model"),
        effective_model=session.get("effective_model") or session.get("model"),
        requested_provider=session.get("requested_provider"),
        effective_provider=session.get("effective_provider") or session.get("provider"),
        fallback_used=bool(session.get("fallback_used")),
        fallback_reason=session.get("fallback_reason"),
        updated_at=session.get("updated_at", ""),
        live_activity=AgentHubLiveActivity(**live_activity) if isinstance(live_activity, dict) else None,
    )


def _is_task_session(session: dict[str, Any], task_id: str) -> bool:
    """Return true only for sessions explicitly linked to this task."""
    return session.get("external_id") == task_id


def _collect_session_events(
    session_ids: list[str], event_type: str | None, turn: int | None, page: int, page_size: int,
) -> tuple[list[AgentHubEvent], int, int]:
    """Collect and combine events from all sessions, sorted by (session, turn, sequence)."""
    all_events: list[AgentHubEvent] = []
    total = 0
    max_turn = 0
    for idx, session_id in enumerate(session_ids):
        result = _fetch_session_events(session_id, event_type=event_type, turn=turn, page=page, page_size=page_size)
        for event in result.get("events", []):
            all_events.append(AgentHubEvent(
                id=event.get("id", ""), session_id=session_id, session_index=idx,
                turn=event.get("turn", 0), sequence=event.get("sequence", 0),
                event_type=event.get("event_type", ""), role=event.get("role"),
                content=event.get("content"), tool_name=event.get("tool_name"),
                tool_input=event.get("tool_input"), tool_output=event.get("tool_output"),
                tokens=event.get("tokens"), duration_ms=event.get("duration_ms"),
                model_used=event.get("model_used"), agent_id=event.get("agent_id"),
                agent_name=event.get("agent_name"), created_at=event.get("created_at", ""),
            ))
        total += result.get("total", 0)
        max_turn = max(max_turn, result.get("max_turn", 0))
    all_events.sort(key=lambda e: (e.session_index, e.turn, e.sequence))
    return all_events, total, max_turn


def _current_attempt_session_ids(task_id: str) -> tuple[bool, list[str]]:
    """Return whether a latest attempt exists plus its Agent Hub session IDs."""
    events = get_events_by_trace(task_id, limit=1000)
    attempt_start = None
    for event in reversed(events):
        if event.get("message") == "Starting autonomous execution":
            attempt_start = event.get("timestamp")
            break

    if attempt_start is None:
        return False, []

    current: list[str] = []
    seen: set[str] = set()
    for event in events:
        if event.get("timestamp") < attempt_start:
            continue
        message = event.get("message") or ""
        match = _SESSION_STARTED_RE.search(message)
        if not match:
            continue
        session_id = match.group(1)
        if session_id not in seen:
            seen.add(session_id)
            current.append(session_id)
    return True, current


def _resolve_task_sessions(
    project_id: str,
    task_id: str,
    *,
    include_history: bool = False,
) -> tuple[list[str], list[AgentHubSessionSummary]]:
    """Resolve task-linked session IDs and summaries, with self-healing fallback.

    Primary source is the persisted task.agent_hub_session_ids array. When that
    array is empty or incomplete, fall back to Agent Hub sessions discovered by
    external_id=task_id and persist any missing links back onto the task.
    """
    stored_session_ids = get_agent_hub_sessions(task_id)
    discovered_sessions = _fetch_task_sessions_by_external_id(project_id, task_id)
    discovered_by_id = {
        str(sid): s
        for s in discovered_sessions
        if isinstance((sid := s.get("id")), str) and sid and _is_task_session(s, task_id)
    }
    for session_id in discovered_by_id:
        if session_id not in stored_session_ids:
            add_agent_hub_session(task_id, session_id)
    session_ids = [*stored_session_ids, *(sid for sid in discovered_by_id if sid not in stored_session_ids)]
    if not include_history:
        current_attempt_seen, current_session_ids = _current_attempt_session_ids(task_id)
        if current_attempt_seen:
            session_ids = current_session_ids
    resolved_session_ids: list[str] = []
    summaries: list[AgentHubSessionSummary] = []
    for sid in session_ids:
        payload = discovered_by_id.get(sid) or _fetch_session_summary(sid)
        if isinstance(payload, dict):
            if not _is_task_session(payload, task_id):
                logger.warning("Skipping non-task Agent Hub session linked to task", task_id=task_id, session_id=sid)
                continue
            summaries.append(_build_session_summary(payload))
        resolved_session_ids.append(sid)
    return resolved_session_ids, summaries


@router.get("/projects/{project_id}/tasks/{task_id}/agent-events", response_model=AgentHubEventsResponse)
async def get_task_agent_events(
    project_id: str,
    task_id: str,
    event_type: str | None = Query(None, description="Filter by event type (user_message, assistant_message, thinking, tool_use, tool_result, memory_inject, memory_cite, error)"),
    turn: int | None = Query(None, description="Filter by turn number"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(500, ge=1, le=500, description="Events per page"),
    include_history: bool = Query(False, description="Include older linked Agent Hub sessions"),
) -> AgentHubEventsResponse:
    """Get Agent Hub session events for a task.

    Returns the complete execution timeline including user/assistant/system messages,
    thinking blocks, tool calls, memory injections, and errors. Events are combined
    from all Agent Hub sessions linked to this task, ordered by (session, turn, sequence).
    """
    verify_task_project(task_id, project_id)
    session_ids, sessions = _resolve_task_sessions(project_id, task_id, include_history=include_history)
    if not session_ids:
        return AgentHubEventsResponse(task_id=task_id, session_ids=[], sessions=[], events=[], total=0, max_turn=0)
    events, total, max_turn = _collect_session_events(session_ids, event_type, turn, page, page_size)
    return AgentHubEventsResponse(task_id=task_id, session_ids=session_ids, sessions=sessions, events=events, total=total, max_turn=max_turn)


@router.get("/projects/{project_id}/tasks/{task_id}/agent-sessions")
async def get_task_agent_sessions(
    project_id: str,
    task_id: str,
    include_history: bool = Query(False, description="Include older linked Agent Hub sessions"),
) -> dict[str, Any]:
    """Get Agent Hub session IDs linked to a task."""
    verify_task_project(task_id, project_id)
    session_ids, summaries = _resolve_task_sessions(project_id, task_id, include_history=include_history)
    return {"task_id": task_id, "session_ids": session_ids, "count": len(session_ids), "sessions": [s.model_dump() for s in summaries]}
