"""HTTP fetch helpers for Agent Hub observability endpoints."""

from __future__ import annotations

import re
from typing import Any

import httpx
from fastapi import HTTPException

from ...logging_config import get_logger
from ...services._agent_hub_config import (
    AGENT_HUB_URL,
    SUMMITFLOW_CLIENT_ID,
    build_agent_hub_headers,
)

logger = get_logger(__name__)

# Module-level constants
DEFAULT_REQUEST_SOURCE = "summitflow-observability"
HTTP_TIMEOUT = 30.0
EMPTY_SESSION_RESULT: dict[str, Any] = {"events": [], "total": 0, "max_turn": 0}
_TASK_ID_PATH_RE = re.compile(r"(?:^|[\\/])(task-[A-Za-z0-9]+)(?=[^A-Za-z0-9]|$)")


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


def _task_id_from_path(path: object) -> str | None:
    if not isinstance(path, str) or not path:
        return None
    match = _TASK_ID_PATH_RE.search(path)
    return match.group(1) if match else None


def _infer_session_task_id(session: dict[str, Any]) -> str | None:
    external_id = session.get("external_id")
    if isinstance(external_id, str) and external_id.startswith("task-"):
        return external_id

    current_branch = session.get("current_branch")
    if isinstance(current_branch, str) and current_branch:
        branch_prefix = current_branch.split("/", 1)[0]
        if branch_prefix.startswith("task-"):
            return branch_prefix

    for key in ("working_dir", "worktree_path", "repo_root"):
        task_id = _task_id_from_path(session.get(key))
        if task_id:
            return task_id
    return None


def _fetch_task_sessions_by_external_id(
    project_id: str,
    task_id: str,
    page_size: int = 100,
) -> list[dict[str, Any]]:
    """Fetch Agent Hub sessions linked to a task by explicit or lane-derived task ID.

    This is the canonical fallback when SummitFlow has not yet persisted
    `agent_hub_session_ids` for a task-scoped wake session.
    """
    url = f"{AGENT_HUB_URL}/api/sessions"
    params = {"project_id": project_id, "status": "active", "page": 1, "page_size": page_size}
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
