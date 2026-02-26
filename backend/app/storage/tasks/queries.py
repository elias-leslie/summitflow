"""Tasks storage - Query operations for listing and filtering tasks."""

from __future__ import annotations

from typing import Any

from psycopg import sql

from ..connection import get_connection
from .columns import TASK_COLUMNS, TASK_COLUMNS_WITH_SPIRIT
from .mapping import row_to_dict, row_to_dict_with_spirit, row_to_dict_with_subtask_summary


def _build_task_filters(
    project_id: str,
    status_filter: str | None = None,
    task_type_filter: str | None = None,
    priority_filter: int | None = None,
    labels_filter: list[str] | None = None,
    orphans_only: bool = False,
) -> tuple[list[str], list[Any]]:
    """Build WHERE conditions and params for task queries."""
    conditions: list[str] = ["t.project_id = %s"]
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
    """List tasks for a project with spirit fields, ordered by priority then creation date."""
    conditions, params = _build_task_filters(
        project_id, status_filter, task_type_filter,
        priority_filter, labels_filter, orphans_only,
    )
    params.extend([limit, offset])

    joined = sql.SQL(" AND ").join(sql.SQL(c) for c in conditions)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            sql.SQL(
                f"SELECT {TASK_COLUMNS_WITH_SPIRIT} FROM tasks t"
                " LEFT JOIN task_spirit ts ON t.id = ts.task_id"
                " WHERE {conditions}"
                " ORDER BY t.priority ASC, t.created_at DESC LIMIT %s OFFSET %s"
            ).format(conditions=joined),
            tuple(params),
        )
        rows = cur.fetchall()
    return [row_to_dict_with_spirit(row) for row in rows]


def count_tasks(
    project_id: str,
    status_filter: str | None = None,
    task_type_filter: str | None = None,
    priority_filter: int | None = None,
    labels_filter: list[str] | None = None,
    orphans_only: bool = False,
) -> int:
    """Count tasks matching the same filters as list_tasks."""
    conditions, params = _build_task_filters(
        project_id, status_filter, task_type_filter,
        priority_filter, labels_filter, orphans_only,
    )
    joined = sql.SQL(" AND ").join(sql.SQL(c) for c in conditions)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            sql.SQL("SELECT COUNT(*) FROM tasks t WHERE {conditions}").format(conditions=joined),
            tuple(params),
        )
        row = cur.fetchone()
    return int(row[0]) if row else 0


def get_tasks_by_enrichment_status(
    project_id: str,
    status: str,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Get tasks with a specific enrichment status, ordered by creation date (newest first)."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT {TASK_COLUMNS} FROM tasks"
            " WHERE project_id = %s AND enrichment_status = %s"
            " ORDER BY created_at DESC LIMIT %s",
            (project_id, status, limit),
        )
        rows = cur.fetchall()
    return [row_to_dict(row) for row in rows]


def list_ready_tasks(project_id: str, limit: int = 50) -> list[dict[str, Any]]:
    """List pending tasks with no incomplete blocking dependencies.

    Returns tasks with spirit fields and subtask_summary, ordered by priority then creation date.
    """
    _not_blocked = (
        "NOT EXISTS (SELECT 1 FROM task_dependencies d"
        " JOIN tasks blocker ON d.depends_on_task_id = blocker.id"
        " WHERE d.task_id = t.id AND d.dependency_type = 'blocks'"
        " AND blocker.status NOT IN ('completed'))"
    )
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {TASK_COLUMNS_WITH_SPIRIT},
                   COALESCE(sub.total, 0) as subtask_total,
                   COALESCE(sub.completed, 0) as subtask_completed
            FROM tasks t
            LEFT JOIN task_spirit ts ON t.id = ts.task_id
            LEFT JOIN (
                SELECT task_id, COUNT(*) as total,
                       SUM(CASE WHEN passes THEN 1 ELSE 0 END) as completed
                FROM task_subtasks GROUP BY task_id
            ) sub ON t.id = sub.task_id
            WHERE t.project_id = %s AND t.status = 'pending' AND {_not_blocked}
            ORDER BY t.priority ASC, t.created_at ASC LIMIT %s
            """,
            (project_id, limit),
        )
        rows = cur.fetchall()
    return [row_to_dict_with_subtask_summary(row) for row in rows]


def list_blocked_tasks(project_id: str, limit: int = 50) -> list[dict[str, Any]]:
    """List pending tasks blocked by incomplete dependencies, ordered by priority then creation."""
    _is_blocked = (
        "EXISTS (SELECT 1 FROM task_dependencies d"
        " JOIN tasks blocker ON d.depends_on_task_id = blocker.id"
        " WHERE d.task_id = t.id AND d.dependency_type = 'blocks'"
        " AND blocker.status NOT IN ('completed'))"
    )
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT DISTINCT {TASK_COLUMNS_WITH_SPIRIT}
            FROM tasks t LEFT JOIN task_spirit ts ON t.id = ts.task_id
            WHERE t.project_id = %s AND t.status = 'pending' AND {_is_blocked}
            ORDER BY t.priority ASC, t.created_at ASC LIMIT %s
            """,
            (project_id, limit),
        )
        rows = cur.fetchall()
    return [row_to_dict_with_spirit(row) for row in rows]


def get_stale_tasks(max_age_days: int = 30, limit: int = 100) -> list[dict[str, Any]]:
    """Get auto-generated pending tasks with no activity for more than max_age_days."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT {TASK_COLUMNS} FROM tasks"
            " WHERE status = 'pending' AND 'auto-generated' = ANY(labels)"
            " AND created_at < NOW() - INTERVAL '%s days'"
            " AND (updated_at IS NULL OR updated_at < NOW() - INTERVAL '%s days')"
            " ORDER BY created_at ASC LIMIT %s",
            (max_age_days, max_age_days, limit),
        )
        rows = cur.fetchall()
    return [row_to_dict(row) for row in rows]


def count_completed_tasks_today(project_id: str) -> int:
    """Count tasks with status 'completed' and updated_at today for a project."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM tasks"
            " WHERE project_id = %s AND status = 'completed' AND DATE(updated_at) = CURRENT_DATE",
            (project_id,),
        )
        row = cur.fetchone()
        return int(row[0]) if row else 0
