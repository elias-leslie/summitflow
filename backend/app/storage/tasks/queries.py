"""Tasks storage - Query operations for listing and filtering tasks.

This module provides task listing, filtering, and ready/blocked queries.
"""

from __future__ import annotations

from typing import Any

from psycopg import sql

from ..connection import get_connection
from .core import (
    EXPECTED_TASK_COLUMNS_WITH_SPIRIT,
    TASK_COLUMNS,
    TASK_COLUMNS_WITH_SPIRIT,
    _row_to_dict,
    _row_to_dict_with_spirit,
)


def _build_task_filters(
    project_id: str,
    status_filter: str | None = None,
    task_type_filter: str | None = None,
    priority_filter: int | None = None,
    labels_filter: list[str] | None = None,
    orphans_only: bool = False,
) -> tuple[list[str], list[Any]]:
    """Build WHERE conditions and params for task queries."""
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
        conditions.append("t.labels @> %s")
        params.append(labels_filter)
    if orphans_only:
        conditions.append("t.capability_id IS NULL")

    return conditions, params


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
    """List tasks for a project with spirit fields.

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
        List of task dicts with spirit fields.
    """
    conditions, params = _build_task_filters(
        project_id, status_filter, task_type_filter,
        priority_filter, labels_filter, orphans_only,
    )
    params.extend([limit, offset])

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            sql.SQL(f"""
            SELECT {TASK_COLUMNS_WITH_SPIRIT}
            FROM tasks t
            LEFT JOIN task_spirit ts ON t.id = ts.task_id
            WHERE {{conditions}}
            ORDER BY t.priority ASC, t.created_at DESC
            LIMIT %s OFFSET %s
            """).format(conditions=sql.SQL(" AND ").join(sql.SQL(c) for c in conditions)),
            tuple(params),
        )
        rows = cur.fetchall()

    return [_row_to_dict_with_spirit(row) for row in rows]


def count_tasks(
    project_id: str,
    status_filter: str | None = None,
    task_type_filter: str | None = None,
    priority_filter: int | None = None,
    labels_filter: list[str] | None = None,
    orphans_only: bool = False,
) -> int:
    """Count tasks matching the same filters as list_tasks.

    Returns:
        Total count of matching tasks (ignoring limit/offset).
    """
    conditions, params = _build_task_filters(
        project_id, status_filter, task_type_filter,
        priority_filter, labels_filter, orphans_only,
    )

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            sql.SQL("""
            SELECT COUNT(*)
            FROM tasks t
            WHERE {conditions}
            """).format(conditions=sql.SQL(" AND ").join(sql.SQL(c) for c in conditions)),
            tuple(params),
        )
        row = cur.fetchone()

    return int(row[0]) if row else 0


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
    """Convert a database row with spirit fields and subtask counts to a task dict.

    Expects 46 columns: 44 task+spirit columns + subtask_total + subtask_completed.
    """
    if row is None:
        raise ValueError("Row cannot be None")
    if len(row) != EXPECTED_TASK_COLUMNS_WITH_SPIRIT + 2:
        raise ValueError(
            f"Expected {EXPECTED_TASK_COLUMNS_WITH_SPIRIT + 2} columns, got {len(row)}"
        )

    # First 44 columns are the task + spirit columns
    task = _row_to_dict_with_spirit(row[:EXPECTED_TASK_COLUMNS_WITH_SPIRIT])

    # Last 2 columns are subtask counts
    subtask_total = row[EXPECTED_TASK_COLUMNS_WITH_SPIRIT]
    subtask_completed = row[EXPECTED_TASK_COLUMNS_WITH_SPIRIT + 1]

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
        List of ready task dicts with spirit fields and subtask_summary,
        ordered by priority then creation date.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {TASK_COLUMNS_WITH_SPIRIT},
                   COALESCE(sub.total, 0) as subtask_total,
                   COALESCE(sub.completed, 0) as subtask_completed
            FROM tasks t
            LEFT JOIN task_spirit ts ON t.id = ts.task_id
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
        List of blocked task dicts with spirit fields and blocking_tasks field added.
    """
    with get_connection() as conn, conn.cursor() as cur:
        # Get blocked tasks
        cur.execute(
            f"""
            SELECT DISTINCT {TASK_COLUMNS_WITH_SPIRIT}
            FROM tasks t
            LEFT JOIN task_spirit ts ON t.id = ts.task_id
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

    return [_row_to_dict_with_spirit(row) for row in rows]


def get_stale_tasks(max_age_days: int = 30, limit: int = 100) -> list[dict[str, Any]]:
    """Get tasks that have been pending without activity for too long.

    A task is considered stale if:
    - Status is 'pending'
    - Has 'auto-generated' label (not user-created)
    - Created more than max_age_days ago
    - No recent updates (updated_at < max_age_days ago)

    Args:
        max_age_days: Number of days without activity to consider stale
        limit: Max results

    Returns:
        List of stale task dicts.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {TASK_COLUMNS}
            FROM tasks
            WHERE status = 'pending'
              AND 'auto-generated' = ANY(labels)
              AND created_at < NOW() - INTERVAL '%s days'
              AND (updated_at IS NULL OR updated_at < NOW() - INTERVAL '%s days')
            ORDER BY created_at ASC
            LIMIT %s
            """,
            (max_age_days, max_age_days, limit),
        )
        rows = cur.fetchall()

    return [_row_to_dict(row) for row in rows]


def count_completed_tasks_today(project_id: str) -> int:
    """Count tasks completed today for a project.

    Args:
        project_id: Project ID

    Returns:
        Number of tasks with status 'completed' and updated_at today
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*)
            FROM tasks
            WHERE project_id = %s
              AND status = 'completed'
              AND DATE(updated_at) = CURRENT_DATE
            """,
            (project_id,),
        )
        row = cur.fetchone()
        return int(row[0]) if row else 0
