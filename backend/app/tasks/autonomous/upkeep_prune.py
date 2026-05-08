"""Prune obsolete auto-generated upkeep tasks while preserving forensic snapshots."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.storage import log_task_event
from app.storage import tasks as task_store
from app.storage.connection import get_cursor

OBSOLETE_WORKED_GRACE_HOURS = 24
PRUNABLE_STATUSES = ("pending", "paused", "failed")


def _has_work(task: dict[str, Any]) -> bool:
    commits = task.get("commits") or []
    return bool(
        task.get("started_at")
        or int(task.get("total_sessions") or 0) > 0
        or (isinstance(commits, list) and commits)
    )


def _is_dormant(task: dict[str, Any], *, grace_hours: int, now: datetime | None = None) -> bool:
    updated_at = task.get("updated_at")
    if not isinstance(updated_at, datetime):
        return True
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=UTC)
    return (now or datetime.now(UTC)) - updated_at >= timedelta(hours=grace_hours)


def close_obsolete_generated_task(
    task: dict[str, Any],
    *,
    reason: str,
    resolved: bool,
    deletion_source: str,
    grace_hours: int = OBSOLETE_WORKED_GRACE_HOURS,
) -> str:
    """Delete unworked generated rows; complete/cancel worked dormant rows."""
    task_id = str(task.get("id") or "")
    if not task_id:
        return "skipped"
    if not _has_work(task):
        deleted = task_store.delete_task(
            task_id,
            deletion_source=deletion_source,
            deletion_reason=reason,
        )
        return "deleted" if deleted else "skipped"
    if not _is_dormant(task, grace_hours=grace_hours):
        return "skipped_active"
    status = "completed" if resolved else "cancelled"
    updated = task_store.update_task_status(
        task_id,
        status,
        error_message=reason,
        validate_transition=False,
    )
    if not updated:
        return "skipped"
    log_task_event(task_id, f"Auto-closed obsolete generated task: {reason}", source="routine_upkeep")
    return status


def _upkeep_signal_tasks(project_id: str, signal_type: str) -> list[dict[str, Any]]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT
                t.id,
                t.status,
                t.started_at,
                t.updated_at,
                t.total_sessions,
                t.commits,
                t.title,
                ts.context -> 'upkeep' ->> 'source_key' AS source_key
            FROM tasks t
            JOIN task_spirit ts ON ts.task_id = t.id
            WHERE t.project_id = %s
              AND t.status = ANY(%s)
              AND 'auto-generated' = ANY(t.labels)
              AND ts.context -> 'upkeep' ->> 'signal_type' = %s
            """,
            (project_id, list(PRUNABLE_STATUSES), signal_type),
        )
        rows = cur.fetchall()
    return [
        {
            "id": row[0],
            "status": row[1],
            "started_at": row[2],
            "updated_at": row[3],
            "total_sessions": row[4],
            "commits": row[5],
            "title": row[6],
            "source_key": row[7],
        }
        for row in rows
    ]


def prune_obsolete_upkeep_signal_tasks(
    project_id: str,
    signal_type: str,
    active_source_keys: set[str],
    *,
    resolved_when_missing: bool = True,
) -> dict[str, int]:
    """Close generated upkeep tasks whose backing signal is no longer active."""
    counts = {"deleted": 0, "completed": 0, "cancelled": 0, "skipped": 0, "skipped_active": 0}
    for task in _upkeep_signal_tasks(project_id, signal_type):
        source_key = str(task.get("source_key") or "")
        if source_key and source_key in active_source_keys:
            counts["skipped"] += 1
            continue
        result = close_obsolete_generated_task(
            task,
            reason=f"Source signal no longer active: {signal_type}:{source_key or 'unknown'}",
            resolved=resolved_when_missing,
            deletion_source=f"routine-upkeep:prune-{signal_type}",
        )
        counts[result] = counts.get(result, 0) + 1
    return counts
