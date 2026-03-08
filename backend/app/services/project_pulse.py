"""Project-wide coordination pulse for cross-agent awareness."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from app.services._agent_hub_config import AGENT_HUB_URL, build_agent_hub_headers
from app.services.workspace_status import build_project_cleanup_status
from app.storage.tasks.queries import list_tasks

_TIMEOUT = 10.0
_TASK_LIMIT = 8
_SESSION_LIMIT = 25


async def _agent_hub_get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Fetch a JSON payload from Agent Hub."""
    headers = build_agent_hub_headers(default_request_source="summitflow-project-pulse")
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.get(f"{AGENT_HUB_URL}{path}", headers=headers, params=params)
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else {}


def _normalize_active_session(session: dict[str, Any], owner_session_ids: set[str], specialist_session_ids: set[str]) -> dict[str, Any]:
    """Return the session fields relevant for coordination summaries."""
    session_id = str(session.get("id") or "")
    if session_id in owner_session_ids:
        lane_role = "owner"
    elif session_id in specialist_session_ids:
        lane_role = "specialist"
    else:
        lane_role = "observer"

    return {
        "id": session_id,
        "lane_role": lane_role,
        "status": session.get("status"),
        "session_type": session.get("session_type"),
        "agent_slug": session.get("agent_slug"),
        "parent_session_id": session.get("parent_session_id"),
        "external_id": session.get("external_id"),
        "current_branch": session.get("current_branch"),
        "working_dir": session.get("working_dir"),
        "requested_model": session.get("requested_model"),
        "effective_model": session.get("effective_model") or session.get("model"),
        "fallback_used": bool(session.get("fallback_used")),
        "fallback_reason": session.get("fallback_reason"),
        "summary_oneliner": session.get("summary_oneliner"),
        "updated_at": session.get("updated_at"),
        "live_activity": session.get("live_activity"),
    }


def _normalize_running_task(task: dict[str, Any]) -> dict[str, Any]:
    """Return compact task fields for pulse summaries."""
    return {
        "id": task.get("id"),
        "title": task.get("title"),
        "status": task.get("status"),
        "task_type": task.get("task_type"),
        "priority": task.get("priority"),
        "updated_at": task.get("updated_at"),
    }


async def build_project_pulse(project_id: str) -> dict[str, Any]:
    """Return the canonical live coordination payload for one project."""
    ownership = await _agent_hub_get(f"/api/ownership/projects/{project_id}/live")
    sessions_payload = await _agent_hub_get(
        "/api/sessions",
        params={"project_id": project_id, "status": "active", "page": 1, "page_size": _SESSION_LIMIT},
    )
    active_owners = ownership.get("active_owners", [])
    active_specialists = ownership.get("active_specialists", [])
    raw_sessions = sessions_payload.get("sessions", [])

    owner_session_ids = {
        str(owner.get("session_id") or "")
        for owner in active_owners
        if isinstance(owner, dict)
    }
    specialist_session_ids = {
        str(session.get("session_id") or "")
        for session in active_specialists
        if isinstance(session, dict)
    }

    active_sessions = [
        _normalize_active_session(session, owner_session_ids, specialist_session_ids)
        for session in raw_sessions
        if isinstance(session, dict)
    ]
    running_tasks = [
        _normalize_running_task(task)
        for task in list_tasks(project_id, status_filter="running", limit=_TASK_LIMIT)
    ]
    cleanup = build_project_cleanup_status(project_id)

    return {
        "project_id": project_id,
        "generated_at": datetime.now(UTC).isoformat(),
        "summary": {
            "running_tasks": len(running_tasks),
            "active_owners": len(active_owners),
            "active_specialists": len(active_specialists),
            "active_sessions": len(active_sessions),
            "active_worktrees": cleanup["active_worktrees"],
            "dirty_worktrees": cleanup["dirty_worktrees"],
            "needs_cleanup": cleanup["needs_cleanup"],
        },
        "running_tasks": running_tasks,
        "active_owners": active_owners,
        "active_specialists": active_specialists,
        "active_sessions": active_sessions,
        "cleanup": cleanup,
    }
