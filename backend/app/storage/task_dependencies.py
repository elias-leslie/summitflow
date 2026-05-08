"""Task dependencies storage layer - Dependency management between tasks."""

from __future__ import annotations

from typing import Any

from .connection import get_connection, get_cursor

_VALID_DEPENDENCY_TYPES = {"blocks", "discovered-from"}

# SQL queries
_SQL_FETCH = """
    SELECT id, task_id, depends_on_task_id, dependency_type, created_at
    FROM task_dependencies
    WHERE task_id = %s AND depends_on_task_id = %s AND dependency_type = %s
"""
_SQL_INSERT = """
    INSERT INTO task_dependencies (task_id, depends_on_task_id, dependency_type)
    VALUES (%s, %s, %s)
    ON CONFLICT (task_id, depends_on_task_id, dependency_type) DO NOTHING
    RETURNING id, task_id, depends_on_task_id, dependency_type, created_at
"""
_SQL_DELETE_TYPED = """
    DELETE FROM task_dependencies
    WHERE task_id = %s AND depends_on_task_id = %s AND dependency_type = %s
    RETURNING id
"""
_SQL_DELETE_ALL = """
    DELETE FROM task_dependencies
    WHERE task_id = %s AND depends_on_task_id = %s
    RETURNING id
"""
_SQL_GET_DEPS = """
    SELECT d.id, d.task_id, d.depends_on_task_id, d.dependency_type, d.created_at,
           t.title as depends_on_title, t.status as depends_on_status
    FROM task_dependencies d
    JOIN tasks t ON d.depends_on_task_id = t.id
    WHERE d.task_id = %s
    ORDER BY d.created_at
"""
_SQL_BLOCKERS = """
    SELECT t.id, t.title, t.status, t.priority
    FROM task_dependencies d
    JOIN tasks t ON d.depends_on_task_id = t.id
    WHERE d.task_id = %s AND d.dependency_type = 'blocks' AND t.status NOT IN ('completed')
    ORDER BY t.priority ASC, t.created_at ASC
"""
_SQL_BLOCKERS_BATCH = """
    SELECT d.task_id, t.id, t.title, t.status, t.priority
    FROM task_dependencies d
    JOIN tasks t ON d.depends_on_task_id = t.id
    WHERE d.task_id = ANY(%s) AND d.dependency_type = 'blocks' AND t.status NOT IN ('completed')
    ORDER BY t.priority ASC, t.created_at ASC
"""
_SQL_IS_BLOCKED = """
    SELECT EXISTS (
        SELECT 1 FROM task_dependencies d
        JOIN tasks t ON d.depends_on_task_id = t.id
        WHERE d.task_id = %s AND d.dependency_type = 'blocks' AND t.status NOT IN ('completed')
    )
"""
_SQL_BLOCKED_DEPENDENTS_BATCH = """
    SELECT d.depends_on_task_id, COUNT(*)::int
    FROM task_dependencies d
    JOIN tasks dependent ON d.task_id = dependent.id
    WHERE d.depends_on_task_id = ANY(%s)
      AND d.dependency_type = 'blocks'
      AND dependent.status NOT IN ('completed')
    GROUP BY d.depends_on_task_id
"""


def _dep_row_to_dict(row: tuple[Any, ...]) -> dict[str, Any]:
    """Convert a dependency row (id, task_id, depends_on_task_id, dependency_type, created_at) to dict."""
    return {"id": row[0], "task_id": row[1], "depends_on_task_id": row[2], "dependency_type": row[3], "created_at": row[4]}


def _validate_dependency(task_id: str, depends_on_task_id: str, dependency_type: str) -> None:
    """Validate dependency arguments. Raises ValueError if invalid."""
    if dependency_type not in _VALID_DEPENDENCY_TYPES:
        raise ValueError(f"Invalid dependency type '{dependency_type}'. Must be one of: {_VALID_DEPENDENCY_TYPES}")
    if task_id == depends_on_task_id:
        raise ValueError("Task cannot depend on itself")


def add_dependency(
    task_id: str,
    depends_on_task_id: str,
    dependency_type: str = "blocks",
) -> dict[str, Any] | None:
    """Add a dependency between two tasks.

    Returns the created dependency dict, or None if constraint violated.
    Raises ValueError if invalid dependency type or self-reference.
    """
    _validate_dependency(task_id, depends_on_task_id, dependency_type)
    with get_connection() as conn, conn.cursor() as cur:
        try:
            cur.execute(_SQL_INSERT, (task_id, depends_on_task_id, dependency_type))
            row = cur.fetchone()
            conn.commit()
            if not row:
                cur.execute(_SQL_FETCH, (task_id, depends_on_task_id, dependency_type))
                row = cur.fetchone()
            return _dep_row_to_dict(row) if row else None
        except Exception as e:
            conn.rollback()
            if "foreign key" in str(e).lower():
                return None
            raise


def remove_dependency(
    task_id: str,
    depends_on_task_id: str,
    dependency_type: str | None = None,
) -> bool:
    """Remove a dependency between two tasks. Returns True if any row was deleted."""
    with get_connection() as conn, conn.cursor() as cur:
        if dependency_type:
            cur.execute(_SQL_DELETE_TYPED, (task_id, depends_on_task_id, dependency_type))
        else:
            cur.execute(_SQL_DELETE_ALL, (task_id, depends_on_task_id))
        result = cur.fetchone()
        conn.commit()
    return result is not None


def get_dependencies(task_id: str) -> list[dict[str, Any]]:
    """Get all dependencies for a task (what this task depends on)."""
    with get_cursor() as cur:
        cur.execute(_SQL_GET_DEPS, (task_id,))
        rows = cur.fetchall()
    return [
        {"id": r[0], "task_id": r[1], "depends_on_task_id": r[2], "dependency_type": r[3],
         "created_at": r[4], "depends_on_title": r[5], "depends_on_status": r[6]}
        for r in rows
    ]


def get_blocking_tasks(task_id: str) -> list[dict[str, Any]]:
    """Get unresolved blocking dependencies for a task (only incomplete blockers)."""
    with get_cursor() as cur:
        cur.execute(_SQL_BLOCKERS, (task_id,))
        rows = cur.fetchall()
    return [{"id": r[0], "title": r[1], "status": r[2], "priority": r[3]} for r in rows]


def get_blocking_tasks_batch(task_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    """Get unresolved blocking dependencies for multiple tasks in a single query.

    Returns a dict mapping task_id to list of blocking task details.
    Tasks with no blockers are omitted.
    """
    if not task_ids:
        return {}
    with get_cursor() as cur:
        cur.execute(_SQL_BLOCKERS_BATCH, (task_ids,))
        rows = cur.fetchall()
    result: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        result.setdefault(row[0], []).append({"id": row[1], "title": row[2], "status": row[3], "priority": row[4]})
    return result


def is_blocked(task_id: str) -> bool:
    """Check if a task has incomplete blocking dependencies."""
    with get_cursor() as cur:
        cur.execute(_SQL_IS_BLOCKED, (task_id,))
        result = cur.fetchone()
    return result[0] if result else False


def count_blocked_dependents_batch(task_ids: list[str]) -> dict[str, int]:
    """Count incomplete tasks each task currently unblocks."""
    if not task_ids:
        return {}
    with get_cursor() as cur:
        cur.execute(_SQL_BLOCKED_DEPENDENTS_BATCH, (task_ids,))
        rows = cur.fetchall()
    return {str(row[0]): int(row[1] or 0) for row in rows}
