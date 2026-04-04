"""Task Events Source - Fetch activity events from tasks table."""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

from ..._sql import static_sql
from ...connection import get_cursor
from ..types import ActivityEvent, TaskMetadata

_TERMINAL_STATUSES = {"completed", "cancelled", "blocked"}


def _build_task_query_params(
    project_id: str | None,
) -> tuple[str, list[str | int]]:
    """Build WHERE clause and params for task query."""
    where_clause = ""
    params: list[str | int] = []

    if project_id:
        where_clause = "WHERE project_id = %s"
        params.append(project_id)

    return where_clause, params


def _fetch_task_rows(
    where_clause: str,
    params: list[str | int],
    limit: int,
) -> list[tuple[Any, ...]]:
    """Execute the task activity query and return raw rows."""
    with get_cursor() as cur:
        cur.execute(
            static_sql(
                f"""
                SELECT id, project_id, title, status, completed_at, updated_at, created_at
                FROM tasks
                {where_clause}
                ORDER BY COALESCE(completed_at, updated_at, created_at) DESC
                LIMIT %s
                """
            ),
            [*params, limit],
        )
        return cur.fetchall()


def _resolve_task_action(
    status: str | None,
    completed_at: datetime | None,
    updated_at: datetime | None,
    created_at: datetime | None,
) -> str:
    """Translate task row timing into a user-facing activity action."""
    if status in _TERMINAL_STATUSES and completed_at is not None:
        return status
    if updated_at and (created_at is None or updated_at > created_at):
        return "updated"
    return "created"


def _row_to_task_event(row: tuple[Any, ...]) -> ActivityEvent:
    """Convert a raw DB row to an ActivityEvent."""
    task_id, proj_id, title, status, completed_at, updated_at, created_at = row
    action = _resolve_task_action(status, completed_at, updated_at, created_at)
    event_time = completed_at or updated_at or created_at

    metadata: TaskMetadata = {
        "task_id": task_id,
        "status": status or "pending",
        "title": title,
        "action": action,
    }

    return {
        "type": "task",
        "message": f"Task {action}: {title}",
        "timestamp": event_time.isoformat() if event_time else None,
        "project_id": proj_id,
        "metadata": cast(dict[str, Any], metadata),
    }


def get_recent_task_events(
    project_id: str | None = None,
    limit: int = 20,
) -> list[ActivityEvent]:
    """Get recent task activity events.

    Args:
        project_id: Filter by project (None for all)
        limit: Max events to return

    Returns:
        List of activity events for recent task creation, updates, and closures
    """
    where_clause, params = _build_task_query_params(project_id)
    rows = _fetch_task_rows(where_clause, params, limit)
    return [_row_to_task_event(row) for row in rows]
