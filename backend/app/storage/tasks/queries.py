"""Tasks storage - Query operations for listing and filtering tasks.

This module provides task listing, filtering, and ready/blocked queries.
"""

from __future__ import annotations

from typing import Any

from psycopg import sql

from ..connection import get_connection
from .core import (
    EXPECTED_TASK_COLUMNS,
    TASK_COLUMNS,
    TASK_COLUMNS_ALIASED,
    _row_to_dict,
)


def list_tasks(
    project_id: str,
    status_filter: str | None = None,
    task_type_filter: str | None = None,
    priority_filter: int | None = None,
    labels_filter: list[str] | None = None,
    orphans_only: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """List tasks for a project.

    Args:
        project_id: Project ID
        status_filter: Optional status filter (pending, running, paused, failed, completed)
        task_type_filter: Optional type filter (task, bug, feature, refactor, debt, regression)
        priority_filter: Optional priority filter (0-4)
        labels_filter: Optional labels filter (task must have ALL specified labels)
        orphans_only: Only return tasks not linked to a capability
        limit: Max results (default 50)
        offset: Result offset

    Returns:
        List of task dicts.
    """
    conditions = ["t.project_id = %s"]
    params: list[Any] = [project_id]

    if status_filter:
        conditions.append("t.status = %s")
        params.append(status_filter)
    if task_type_filter:
        conditions.append("t.task_type = %s")
        params.append(task_type_filter)
    if priority_filter is not None:
        conditions.append("t.priority = %s")
        params.append(priority_filter)
    if labels_filter:
        # Task must contain all specified labels
        conditions.append("t.labels @> %s")
        params.append(labels_filter)
    if orphans_only:
        conditions.append("t.capability_id IS NULL")

    params.extend([limit, offset])

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            sql.SQL(f"""
            SELECT {TASK_COLUMNS_ALIASED}
            FROM tasks t
            WHERE {{conditions}}
            ORDER BY t.priority ASC, t.created_at DESC
            LIMIT %s OFFSET %s
            """).format(conditions=sql.SQL(" AND ").join(sql.SQL(c) for c in conditions)),
            tuple(params),
        )
        rows = cur.fetchall()

    return [_row_to_dict(row) for row in rows]


def get_tasks_by_enrichment_status(
    project_id: str,
    status: str,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Get all tasks with a specific enrichment status.

    Args:
        project_id: Project ID
        status: Enrichment status (none, draft, enriching, review, discussing, accepted, failed)
        limit: Max results (default 50)

    Returns:
        List of task dicts ordered by creation date (newest first).
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {TASK_COLUMNS}
            FROM tasks
            WHERE project_id = %s AND enrichment_status = %s
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (project_id, status, limit),
        )
        rows = cur.fetchall()

    return [_row_to_dict(row) for row in rows]


def _row_to_dict_with_subtask_summary(row: tuple[Any, ...]) -> dict[str, Any]:
    """Convert a database row with subtask counts to a task dict.

    Expects 36 columns: 34 task columns + subtask_total + subtask_completed.
    """
    if row is None:
        raise ValueError("Row cannot be None")
    if len(row) != EXPECTED_TASK_COLUMNS + 2:
        raise ValueError(f"Expected {EXPECTED_TASK_COLUMNS + 2} columns, got {len(row)}")

    # First 34 columns are the standard task columns
    task = _row_to_dict(row[:EXPECTED_TASK_COLUMNS])

    # Last 2 columns are subtask counts
    subtask_total = row[EXPECTED_TASK_COLUMNS]
    subtask_completed = row[EXPECTED_TASK_COLUMNS + 1]

    # Calculate progress percent
    progress_percent = 0.0
    if subtask_total > 0:
        progress_percent = round((subtask_completed / subtask_total) * 100, 1)

    task["subtask_summary"] = {
        "total": subtask_total,
        "completed": subtask_completed,
        "next_subtask_id": None,  # Would require additional query to determine
        "progress_percent": progress_percent,
    }

    return task


def list_ready_tasks(project_id: str, limit: int = 50) -> list[dict[str, Any]]:
    """List tasks that are not blocked by dependencies.

    A task is "ready" if:
    - Status is 'pending' (not started)
    - Has no incomplete blocking dependencies

    Args:
        project_id: Project ID
        limit: Max results (default 50)

    Returns:
        List of ready task dicts with subtask_summary, ordered by priority then creation date.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {TASK_COLUMNS_ALIASED},
                   COALESCE(sub.total, 0) as subtask_total,
                   COALESCE(sub.completed, 0) as subtask_completed
            FROM tasks t
            LEFT JOIN (
                SELECT task_id,
                       COUNT(*) as total,
                       SUM(CASE WHEN passes THEN 1 ELSE 0 END) as completed
                FROM task_subtasks
                GROUP BY task_id
            ) sub ON t.id = sub.task_id
            WHERE t.project_id = %s
              AND t.status = 'pending'
              AND NOT EXISTS (
                  SELECT 1 FROM task_dependencies d
                  JOIN tasks blocker ON d.depends_on_task_id = blocker.id
                  WHERE d.task_id = t.id
                    AND d.dependency_type = 'blocks'
                    AND blocker.status NOT IN ('completed')
              )
            ORDER BY t.priority ASC, t.created_at ASC
            LIMIT %s
            """,
            (project_id, limit),
        )
        rows = cur.fetchall()

    return [_row_to_dict_with_subtask_summary(row) for row in rows]


def list_blocked_tasks(project_id: str, limit: int = 50) -> list[dict[str, Any]]:
    """List tasks that are blocked by incomplete dependencies.

    Args:
        project_id: Project ID
        limit: Max results (default 50)

    Returns:
        List of blocked task dicts with blocking_tasks field added.
    """
    with get_connection() as conn, conn.cursor() as cur:
        # Get blocked tasks
        cur.execute(
            f"""
            SELECT DISTINCT {TASK_COLUMNS_ALIASED}
            FROM tasks t
            WHERE t.project_id = %s
              AND t.status = 'pending'
              AND EXISTS (
                  SELECT 1 FROM task_dependencies d
                  JOIN tasks blocker ON d.depends_on_task_id = blocker.id
                  WHERE d.task_id = t.id
                    AND d.dependency_type = 'blocks'
                    AND blocker.status NOT IN ('completed')
              )
            ORDER BY t.priority ASC, t.created_at ASC
            LIMIT %s
            """,
            (project_id, limit),
        )
        rows = cur.fetchall()

    return [_row_to_dict(row) for row in rows]
