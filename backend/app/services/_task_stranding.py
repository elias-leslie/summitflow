"""Task stranding detection and ownership extraction for project pulse."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.utils.datetime_helpers import parse_iso_datetime

_STRANDED_TASK_MINUTES = 2


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


def _extract_ownership_sets(
    active_owners: list[dict[str, Any]],
    active_specialists: list[dict[str, Any]],
) -> tuple[set[str], set[str], set[str], set[str]]:
    """Extract session and task ID sets from ownership records."""
    owner_session_ids = {str(o.get("session_id") or "") for o in active_owners if isinstance(o, dict)}
    owner_task_ids = {str(o.get("task_id") or "") for o in active_owners if isinstance(o, dict) and o.get("task_id")}
    specialist_session_ids = {str(s.get("session_id") or "") for s in active_specialists if isinstance(s, dict)}
    specialist_task_ids = {str(s.get("task_id") or "") for s in active_specialists if isinstance(s, dict) and s.get("task_id")}
    return owner_session_ids, owner_task_ids, specialist_session_ids, specialist_task_ids


def _task_is_stranded(
    task: dict[str, Any],
    owner_task_ids: set[str],
    specialist_task_ids: set[str],
    session_linked_task_ids: set[str],
) -> bool:
    """Return True when a running task appears to have lost its live execution lane."""
    task_id = str(task.get("id") or "")
    if not task_id:
        return False
    if task_id in owner_task_ids or task_id in specialist_task_ids:
        return False
    if task_id in session_linked_task_ids:
        return False
    updated_at = parse_iso_datetime(task.get("updated_at"))
    if updated_at is None:
        return True
    age_minutes = (datetime.now(UTC) - updated_at).total_seconds() / 60
    return age_minutes >= _STRANDED_TASK_MINUTES


def _partition_running_tasks(
    tasks: list[dict[str, Any]],
    owner_task_ids: set[str],
    specialist_task_ids: set[str],
    session_linked_task_ids: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split task rows into live running work and stranded remnants."""
    running: list[dict[str, Any]] = []
    stranded: list[dict[str, Any]] = []
    for task in tasks:
        if _task_is_stranded(task, owner_task_ids, specialist_task_ids, session_linked_task_ids):
            stranded.append(task)
        else:
            running.append(task)
    return running, stranded
