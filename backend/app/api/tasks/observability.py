"""Tasks API - Observability endpoints for Agent Hub integration.

Provides endpoints to fetch Agent Hub session events for task execution
observability, including thinking blocks, tool calls, memory events, etc.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from ...logging_config import get_logger
from ...storage.tasks.core import add_agent_hub_session, get_agent_hub_sessions

# Re-export helpers so existing patch targets (tests) remain valid
from ._observability_helpers import (  # noqa: F401
    DEFAULT_REQUEST_SOURCE,
    EMPTY_SESSION_RESULT,
    HTTP_TIMEOUT,
    _fetch_session_events,
    _fetch_session_summary,
    _fetch_task_sessions_by_external_id,
    _infer_session_task_id,
    _task_id_from_path,
)
from ._observability_models import (
    AgentHubEvent,
    AgentHubEventsResponse,
    AgentHubLiveActivity,
    AgentHubSessionSummary,
)
from .helpers import verify_task_project

logger = get_logger(__name__)
router = APIRouter()


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


def _resolve_task_sessions(
    project_id: str,
    task_id: str,
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
        if isinstance((sid := s.get("id")), str) and sid
    }
    for session_id in discovered_by_id:
        if session_id not in stored_session_ids:
            add_agent_hub_session(task_id, session_id)
    session_ids = [*stored_session_ids, *(sid for sid in discovered_by_id if sid not in stored_session_ids)]
    summaries: list[AgentHubSessionSummary] = []
    for sid in session_ids:
        payload = discovered_by_id.get(sid) or _fetch_session_summary(sid)
        if isinstance(payload, dict):
            summaries.append(_build_session_summary(payload))
    return session_ids, summaries


@router.get("/projects/{project_id}/tasks/{task_id}/agent-events", response_model=AgentHubEventsResponse)
async def get_task_agent_events(
    project_id: str,
    task_id: str,
    event_type: str | None = Query(None, description="Filter by event type (user_message, assistant_message, thinking, tool_use, tool_result, memory_inject, memory_cite, error)"),
    turn: int | None = Query(None, description="Filter by turn number"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(500, ge=1, le=500, description="Events per page"),
) -> AgentHubEventsResponse:
    """Get Agent Hub session events for a task.

    Returns the complete execution timeline including user/assistant/system messages,
    thinking blocks, tool calls, memory injections, and errors. Events are combined
    from all Agent Hub sessions linked to this task, ordered by (session, turn, sequence).
    """
    verify_task_project(task_id, project_id)
    session_ids, sessions = _resolve_task_sessions(project_id, task_id)
    if not session_ids:
        return AgentHubEventsResponse(task_id=task_id, session_ids=[], sessions=[], events=[], total=0, max_turn=0)
    events, total, max_turn = _collect_session_events(session_ids, event_type, turn, page, page_size)
    return AgentHubEventsResponse(task_id=task_id, session_ids=session_ids, sessions=sessions, events=events, total=total, max_turn=max_turn)


@router.get("/projects/{project_id}/tasks/{task_id}/agent-sessions")
async def get_task_agent_sessions(project_id: str, task_id: str) -> dict[str, Any]:
    """Get Agent Hub session IDs linked to a task."""
    verify_task_project(task_id, project_id)
    session_ids, summaries = _resolve_task_sessions(project_id, task_id)
    return {"task_id": task_id, "session_ids": session_ids, "count": len(session_ids), "sessions": [s.model_dump() for s in summaries]}
