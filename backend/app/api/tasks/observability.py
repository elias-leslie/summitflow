"""Tasks API - Observability endpoints for Agent Hub integration.

Provides endpoints to fetch Agent Hub session events for task execution
observability, including thinking blocks, tool calls, memory events, etc.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ...logging_config import get_logger
from ...services._agent_hub_config import AGENT_HUB_URL, build_agent_hub_headers
from ...storage.tasks.core import get_agent_hub_sessions
from .helpers import verify_task_project

logger = get_logger(__name__)
router = APIRouter()

# Constants
DEFAULT_REQUEST_SOURCE = "summitflow-observability"
HTTP_TIMEOUT = 30.0
EMPTY_SESSION_RESULT: dict[str, Any] = {"events": [], "total": 0, "max_turn": 0}


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


class AgentHubEventsResponse(BaseModel):
    """Response containing Agent Hub events for a task."""
    task_id: str
    session_ids: list[str]
    events: list[AgentHubEvent]
    total: int
    max_turn: int


def _load_client_id() -> str:
    """Load Agent Hub client ID from ~/.env.local."""
    env_file = Path.home() / ".env.local"
    creds: dict[str, str] = {}
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                key, val = line.split("=", 1)
                creds[key.strip()] = val.strip()
    client_id = (
        os.getenv("SUMMITFLOW_CLIENT_ID")
        or creds.get("SUMMITFLOW_CLIENT_ID")
        or creds.get("CONSULT_CLIENT_ID")
    )
    if not client_id:
        raise HTTPException(status_code=500, detail="Missing SUMMITFLOW_CLIENT_ID credential for Agent Hub")
    return client_id


def _fetch_session_events(
    session_id: str,
    event_type: str | None = None,
    turn: int | None = None,
    page: int = 1,
    page_size: int = 500,
) -> dict[str, Any]:
    """Fetch events from Agent Hub for a single session."""
    client_id = _load_client_id()
    headers = build_agent_hub_headers(
        client_id=client_id,
        default_request_source=DEFAULT_REQUEST_SOURCE,
    )
    params: dict[str, Any] = {"page": page, "page_size": page_size}
    if event_type:
        params["event_type"] = event_type
    if turn is not None:
        params["turn"] = turn
    agent_hub_url = AGENT_HUB_URL
    url = f"{agent_hub_url}/api/sessions/{session_id}/events"
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            response = client.get(url, headers=headers, params=params)
        if response.status_code == 404:
            return EMPTY_SESSION_RESULT
        if response.status_code >= 400:
            logger.warning("Agent Hub API error", session_id=session_id, status=response.status_code, detail=response.text[:200])
            return EMPTY_SESSION_RESULT
        return dict(response.json())
    except httpx.ConnectError:
        logger.warning("Cannot connect to Agent Hub", url=agent_hub_url)
        return EMPTY_SESSION_RESULT
    except Exception as e:
        logger.error("Failed to fetch Agent Hub events", error=str(e))
        return EMPTY_SESSION_RESULT


def _build_agent_event(event: dict[str, Any], session_id: str, session_idx: int) -> AgentHubEvent:
    """Build an AgentHubEvent from a raw event dict."""
    return AgentHubEvent(
        id=event.get("id", ""), session_id=session_id, session_index=session_idx,
        turn=event.get("turn", 0), sequence=event.get("sequence", 0),
        event_type=event.get("event_type", ""), role=event.get("role"),
        content=event.get("content"), tool_name=event.get("tool_name"),
        tool_input=event.get("tool_input"), tool_output=event.get("tool_output"),
        tokens=event.get("tokens"), duration_ms=event.get("duration_ms"),
        model_used=event.get("model_used"), agent_id=event.get("agent_id"),
        agent_name=event.get("agent_name"), created_at=event.get("created_at", ""),
    )


def _collect_session_events(
    session_ids: list[str], event_type: str | None, turn: int | None, page: int, page_size: int,
) -> tuple[list[AgentHubEvent], int, int]:
    """Collect and combine events from all sessions, sorted by (session, turn, sequence)."""
    all_events: list[AgentHubEvent] = []
    total = 0
    max_turn = 0
    for session_idx, session_id in enumerate(session_ids):
        result = _fetch_session_events(session_id, event_type=event_type, turn=turn, page=page, page_size=page_size)
        for event in result.get("events", []):
            all_events.append(_build_agent_event(event, session_id, session_idx))
        total += result.get("total", 0)
        max_turn = max(max_turn, result.get("max_turn", 0))
    all_events.sort(key=lambda e: (e.session_index, e.turn, e.sequence))
    return all_events, total, max_turn


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
    session_ids = get_agent_hub_sessions(task_id)
    if not session_ids:
        return AgentHubEventsResponse(task_id=task_id, session_ids=[], events=[], total=0, max_turn=0)
    events, total, max_turn = _collect_session_events(session_ids, event_type, turn, page, page_size)
    return AgentHubEventsResponse(task_id=task_id, session_ids=session_ids, events=events, total=total, max_turn=max_turn)


@router.get("/projects/{project_id}/tasks/{task_id}/agent-sessions")
async def get_task_agent_sessions(project_id: str, task_id: str) -> dict[str, Any]:
    """Get Agent Hub session IDs linked to a task."""
    verify_task_project(task_id, project_id)
    session_ids = get_agent_hub_sessions(task_id)
    return {"task_id": task_id, "session_ids": session_ids, "count": len(session_ids)}
