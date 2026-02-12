"""Task Events Source - Fetch activity events from tasks table."""

from __future__ import annotations

from typing import Any, cast

from ...connection import get_connection
from ..types import ActivityEvent, TaskMetadata


def get_recent_task_events(
    project_id: str | None = None,
    limit: int = 20,
) -> list[ActivityEvent]:
    """Get recent task completion events.

    Args:
        project_id: Filter by project (None for all)
        limit: Max events to return

    Returns:
        List of activity events for completed/closed tasks
    """
    where_clause = "WHERE status IN ('completed', 'cancelled', 'blocked')"
    params: list[str | int] = []

    if project_id:
        where_clause += " AND project_id = %s"
        params.append(project_id)

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT id, project_id, title, status, completed_at, created_at
            FROM tasks
            {where_clause}
            ORDER BY COALESCE(completed_at, created_at) DESC
            LIMIT %s
            """,
            [*params, limit],
        )
        rows = cur.fetchall()

    events: list[ActivityEvent] = []
    for row in rows:
        task_id, proj_id, title, status, completed_at, created_at = row
        event_time = completed_at or created_at

        metadata: TaskMetadata = {
            "task_id": task_id,
            "status": status,
            "title": title,
        }

        events.append({
            "type": "task",
            "message": f"Task {status}: {title}",
            "timestamp": event_time.isoformat() if event_time else None,
            "project_id": proj_id,
            "metadata": cast(dict[str, Any], metadata),
        })
    return events
