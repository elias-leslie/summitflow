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
_OBSERVER_FRESH_MINUTES = 90
_STRANDED_TASK_MINUTES = 2


async def _agent_hub_get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Fetch a JSON payload from Agent Hub."""
    headers = build_agent_hub_headers(default_request_source="summitflow-project-pulse")
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.get(f"{AGENT_HUB_URL}{path}", headers=headers, params=params)
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else {}


def _parse_iso_timestamp(value: Any) -> datetime | None:
    """Parse an ISO timestamp from Agent Hub session payloads."""
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


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
        "worktree_path": session.get("worktree_path"),
        "repo_root": session.get("repo_root"),
        "host": session.get("host"),
        "tmux_session_name": session.get("tmux_session_name"),
        "scope_confidence": session.get("scope_confidence"),
        "declared_scope_paths": session.get("declared_scope_paths") or [],
        "observed_read_paths": session.get("observed_read_paths") or [],
        "observed_write_paths": session.get("observed_write_paths") or [],
        "requested_model": session.get("requested_model"),
        "effective_model": session.get("effective_model") or session.get("model"),
        "fallback_used": bool(session.get("fallback_used")),
        "fallback_reason": session.get("fallback_reason"),
        "summary_oneliner": session.get("summary_oneliner"),
        "updated_at": session.get("updated_at"),
        "live_activity": session.get("live_activity"),
    }


def _include_active_session(session: dict[str, Any]) -> bool:
    """Keep only sessions that are plausibly live enough for coordination."""
    live_activity = session.get("live_activity")
    if isinstance(live_activity, dict):
        return True
    updated_at = _parse_iso_timestamp(session.get("updated_at"))
    if updated_at is None:
        return False
    age_minutes = (datetime.now(UTC) - updated_at).total_seconds() / 60
    return age_minutes <= _OBSERVER_FRESH_MINUTES


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


def _task_is_stranded(task: dict[str, Any], owner_task_ids: set[str], specialist_task_ids: set[str]) -> bool:
    """Return True when a running task appears to have lost its live execution lane."""
    task_id = str(task.get("id") or "")
    if not task_id:
        return False
    if task_id in owner_task_ids or task_id in specialist_task_ids:
        return False
    updated_at = _parse_iso_timestamp(task.get("updated_at"))
    if updated_at is None:
        return True
    age_minutes = (datetime.now(UTC) - updated_at).total_seconds() / 60
    return age_minutes >= _STRANDED_TASK_MINUTES


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
    owner_task_ids = {
        str(owner.get("task_id") or "")
        for owner in active_owners
        if isinstance(owner, dict) and owner.get("task_id")
    }
    specialist_session_ids = {
        str(session.get("session_id") or "")
        for session in active_specialists
        if isinstance(session, dict)
    }
    specialist_task_ids = {
        str(session.get("task_id") or "")
        for session in active_specialists
        if isinstance(session, dict) and session.get("task_id")
    }

    active_sessions = [
        _normalize_active_session(session, owner_session_ids, specialist_session_ids)
        for session in raw_sessions
        if isinstance(session, dict) and _include_active_session(session)
    ]
    running_tasks = [
        _normalize_running_task(task)
        for task in list_tasks(project_id, status_filter="running", limit=_TASK_LIMIT)
    ]
    stranded_tasks = [
        task for task in running_tasks
        if _task_is_stranded(task, owner_task_ids, specialist_task_ids)
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
            "stranded_tasks": len(stranded_tasks),
        },
        "running_tasks": running_tasks,
        "stranded_tasks": stranded_tasks,
        "active_owners": active_owners,
        "active_specialists": active_specialists,
        "active_sessions": active_sessions,
        "cleanup": cleanup,
    }
