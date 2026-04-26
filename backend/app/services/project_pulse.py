"""Project-wide coordination pulse for cross-agent awareness."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from app.services._agent_hub_config import AGENT_HUB_URL, build_agent_hub_headers
from app.services._session_classifier import _bucket_sessions, _count_reapable
from app.services._task_stranding import (
    _extract_ownership_sets,
    _normalize_running_task,
    _partition_running_tasks,
)
from app.services.workspace_status import build_project_cleanup_status
from app.storage.tasks.queries import list_tasks

_TIMEOUT = 10.0
_TASK_LIMIT = 8
_SESSION_LIMIT = 25
_RUNNING_STATUS = "running"
_SESSIONS_API = "/api/sessions"


async def _agent_hub_get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Fetch a JSON payload from Agent Hub."""
    headers = build_agent_hub_headers(default_request_source="summitflow-project-pulse")
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.get(f"{AGENT_HUB_URL}{path}", headers=headers, params=params)
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else {}


def _filter_ownership_by_active_sessions(
    records: Any,
    active_session_ids: set[str],
) -> list[dict[str, Any]]:
    """Keep ownership rows only when backed by an active session row."""
    if not isinstance(records, list):
        return []
    filtered: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        session_id = str(record.get("session_id") or "")
        if session_id and session_id in active_session_ids:
            filtered.append(record)
    return filtered


async def build_project_pulse(project_id: str) -> dict[str, Any]:
    """Return the canonical live coordination payload for one project."""
    ownership = await _agent_hub_get(f"/api/ownership/projects/{project_id}/live")
    sessions_payload = await _agent_hub_get(
        _SESSIONS_API,
        params={"project_id": project_id, "status": "active", "page": 1, "page_size": _SESSION_LIMIT},
    )
    raw_active_owners = ownership.get("active_owners", [])
    raw_active_specialists = ownership.get("active_specialists", [])
    raw_sessions = sessions_payload.get("sessions", [])

    owner_session_ids, owner_task_ids, specialist_session_ids, specialist_task_ids = (
        _extract_ownership_sets(raw_active_owners, raw_active_specialists)
    )
    active_sessions, stale_sessions, session_linked_task_ids = _bucket_sessions(
        raw_sessions, owner_session_ids, specialist_session_ids
    )
    active_session_ids = {str(session.get("id") or "") for session in active_sessions}
    active_owners = _filter_ownership_by_active_sessions(raw_active_owners, active_session_ids)
    active_specialists = _filter_ownership_by_active_sessions(
        raw_active_specialists, active_session_ids
    )
    _, owner_task_ids, _, specialist_task_ids = _extract_ownership_sets(
        active_owners, active_specialists
    )
    raw_running_tasks = [
        _normalize_running_task(t)
        for t in list_tasks(project_id, status_filter=_RUNNING_STATUS, limit=_TASK_LIMIT)
    ]
    running_tasks, stranded_tasks = _partition_running_tasks(
        raw_running_tasks, owner_task_ids, specialist_task_ids, session_linked_task_ids
    )
    cleanup = build_project_cleanup_status(project_id)
    return {
        "project_id": project_id,
        "generated_at": datetime.now(UTC).isoformat(),
        "summary": {
            "running_tasks": len(running_tasks),
            "active_owners": len(active_owners),
            "active_specialists": len(active_specialists),
            "active_sessions": len(active_sessions),
            "stale_sessions": len(stale_sessions),
            "reapable_sessions": _count_reapable(stale_sessions),
            "active_checkpoints": cleanup["active_checkpoints"],
            "dirty_checkpoints": cleanup["dirty_checkpoints"],
            "needs_cleanup": cleanup["needs_cleanup"],
            "stranded_tasks": len(stranded_tasks),
        },
        "running_tasks": running_tasks,
        "stranded_tasks": stranded_tasks,
        "active_owners": active_owners,
        "active_specialists": active_specialists,
        "active_sessions": active_sessions,
        "stale_sessions": stale_sessions,
        "cleanup": cleanup,
    }
