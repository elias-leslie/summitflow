"""Task dependencies storage layer - Dependency management between tasks.

This module provides data access for task dependency relationships.
"""

from __future__ import annotations

from typing import Any

from .connection import get_connection


def add_dependency(
    task_id: str,
    depends_on_task_id: str,
    dependency_type: str = "blocks",
) -> dict[str, Any] | None:
    """Add a dependency between two tasks.

    Args:
        task_id: The task that has the dependency
        depends_on_task_id: The task that must complete first
        dependency_type: Type of dependency ('blocks', 'discovered-from')

    Returns:
        The created dependency dict, or None if constraint violated.

    Raises:
        ValueError: If invalid dependency type or self-reference.
    """
    valid_types = {"blocks", "discovered-from"}
    if dependency_type not in valid_types:
        raise ValueError(f"Invalid dependency type '{dependency_type}'. Must be one of: {valid_types}")

    if task_id == depends_on_task_id:
        raise ValueError("Task cannot depend on itself")

    with get_connection() as conn, conn.cursor() as cur:
        try:
            cur.execute(
                """
                INSERT INTO task_dependencies (task_id, depends_on_task_id, dependency_type)
                VALUES (%s, %s, %s)
                ON CONFLICT (task_id, depends_on_task_id, dependency_type) DO NOTHING
                RETURNING id, task_id, depends_on_task_id, dependency_type, created_at
                """,
                (task_id, depends_on_task_id, dependency_type),
            )
            row = cur.fetchone()
            conn.commit()

            if not row:
                # Already exists
                cur.execute(
                    """
                    SELECT id, task_id, depends_on_task_id, dependency_type, created_at
                    FROM task_dependencies
                    WHERE task_id = %s AND depends_on_task_id = %s AND dependency_type = %s
                    """,
                    (task_id, depends_on_task_id, dependency_type),
                )
                row = cur.fetchone()

            return _dep_row_to_dict(row) if row else None
        except Exception as e:
            conn.rollback()
            # Foreign key violation
            if "foreign key" in str(e).lower():
                return None
            raise


def remove_dependency(
    task_id: str,
    depends_on_task_id: str,
    dependency_type: str | None = None,
) -> bool:
    """Remove a dependency between two tasks.

    Args:
        task_id: The task that has the dependency
        depends_on_task_id: The task being depended on
        dependency_type: Optional type filter (removes all types if not specified)

    Returns:
        True if any dependency was removed, False otherwise.
    """
    with get_connection() as conn, conn.cursor() as cur:
        if dependency_type:
            cur.execute(
                """
                DELETE FROM task_dependencies
                WHERE task_id = %s AND depends_on_task_id = %s AND dependency_type = %s
                RETURNING id
                """,
                (task_id, depends_on_task_id, dependency_type),
            )
        else:
            cur.execute(
                """
                DELETE FROM task_dependencies
                WHERE task_id = %s AND depends_on_task_id = %s
                RETURNING id
                """,
                (task_id, depends_on_task_id),
            )
        result = cur.fetchone()
        conn.commit()

    return result is not None


def get_dependencies(task_id: str) -> list[dict[str, Any]]:
    """Get all dependencies for a task (what this task depends on).

    Args:
        task_id: Task ID

    Returns:
        List of dependency dicts with depends_on_task details.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT d.id, d.task_id, d.depends_on_task_id, d.dependency_type, d.created_at,
                   t.title as depends_on_title, t.status as depends_on_status
            FROM task_dependencies d
            JOIN tasks t ON d.depends_on_task_id = t.id
            WHERE d.task_id = %s
            ORDER BY d.created_at
            """,
            (task_id,),
        )
        rows = cur.fetchall()

    return [
        {
            "id": row[0],
            "task_id": row[1],
            "depends_on_task_id": row[2],
            "dependency_type": row[3],
            "created_at": row[4],
            "depends_on_title": row[5],
            "depends_on_status": row[6],
        }
        for row in rows
    ]


def get_dependents(task_id: str) -> list[dict[str, Any]]:
    """Get all tasks that depend on this task.

    Args:
        task_id: Task ID

    Returns:
        List of dependency dicts with dependent task details.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT d.id, d.task_id, d.depends_on_task_id, d.dependency_type, d.created_at,
                   t.title as dependent_title, t.status as dependent_status
            FROM task_dependencies d
            JOIN tasks t ON d.task_id = t.id
            WHERE d.depends_on_task_id = %s
            ORDER BY d.created_at
            """,
            (task_id,),
        )
        rows = cur.fetchall()

    return [
        {
            "id": row[0],
            "task_id": row[1],
            "depends_on_task_id": row[2],
            "dependency_type": row[3],
            "created_at": row[4],
            "dependent_title": row[5],
            "dependent_status": row[6],
        }
        for row in rows
    ]


def get_blocking_tasks(task_id: str) -> list[dict[str, Any]]:
    """Get unresolved blocking dependencies for a task.

    Args:
        task_id: Task ID

    Returns:
        List of blocking task details (only incomplete blockers).
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT t.id, t.title, t.status, t.priority
            FROM task_dependencies d
            JOIN tasks t ON d.depends_on_task_id = t.id
            WHERE d.task_id = %s
              AND d.dependency_type = 'blocks'
              AND t.status NOT IN ('completed')
            ORDER BY t.priority ASC, t.created_at ASC
            """,
            (task_id,),
        )
        rows = cur.fetchall()

    return [
        {
            "id": row[0],
            "title": row[1],
            "status": row[2],
            "priority": row[3],
        }
        for row in rows
    ]


def is_blocked(task_id: str) -> bool:
    """Check if a task is blocked by unresolved dependencies.

    Args:
        task_id: Task ID

    Returns:
        True if the task has incomplete blocking dependencies.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT EXISTS (
                SELECT 1 FROM task_dependencies d
                JOIN tasks t ON d.depends_on_task_id = t.id
                WHERE d.task_id = %s
                  AND d.dependency_type = 'blocks'
                  AND t.status NOT IN ('completed')
            )
            """,
            (task_id,),
        )
        result = cur.fetchone()

    return result[0] if result else False


def _dep_row_to_dict(row: tuple) -> dict[str, Any]:
    """Convert a dependency row to dict."""
    return {
        "id": row[0],
        "task_id": row[1],
        "depends_on_task_id": row[2],
        "dependency_type": row[3],
        "created_at": row[4],
    }
