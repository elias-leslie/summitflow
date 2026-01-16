"""Subtask Dependencies storage - DAG operations for subtask execution order.

Handles the subtask_dependencies table which tracks dependencies between
subtasks within a task (subtask A depends on subtask B).

Includes:
- CRUD operations for dependencies
- Topological sort for execution order
- Cycle detection (also enforced by DB trigger)
- Blocking status checks
"""

from __future__ import annotations

import logging
from typing import Any

from psycopg.rows import TupleRow

from .connection import get_connection

logger = logging.getLogger(__name__)

# Expected columns for validation
EXPECTED_COLUMNS = 4  # id, subtask_id, depends_on_subtask_id, created_at


def _row_to_dict(row: TupleRow | tuple[Any, ...] | None) -> dict[str, Any] | None:
    """Convert a subtask_dependencies row to a dictionary."""
    if row is None:
        return None
    if len(row) != EXPECTED_COLUMNS:
        raise ValueError(
            f"Expected {EXPECTED_COLUMNS} columns for subtask_dependencies, got {len(row)}"
        )
    return {
        "id": row[0],
        "subtask_id": row[1],
        "depends_on_subtask_id": row[2],
        "created_at": row[3].isoformat() if row[3] else None,
    }


class CycleError(Exception):
    """Raised when adding a dependency would create a cycle."""

    def __init__(self, message: str, cycle_path: list[str] | None = None):
        super().__init__(message)
        self.cycle_path = cycle_path or []


def add_dependency(subtask_id: str, depends_on_subtask_id: str) -> dict[str, Any] | None:
    """Add a dependency: subtask_id depends on depends_on_subtask_id.

    Args:
        subtask_id: The subtask that has the dependency
        depends_on_subtask_id: The subtask that must complete first

    Returns:
        Created dependency record or None if already exists

    Raises:
        CycleError: If adding this dependency would create a cycle
        ValueError: If subtask_id == depends_on_subtask_id
    """
    if subtask_id == depends_on_subtask_id:
        raise ValueError("Subtask cannot depend on itself")

    with get_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                """
                INSERT INTO subtask_dependencies (subtask_id, depends_on_subtask_id)
                VALUES (%s, %s)
                ON CONFLICT (subtask_id, depends_on_subtask_id) DO NOTHING
                RETURNING *
                """,
                (subtask_id, depends_on_subtask_id),
            )
            row = cur.fetchone()
            conn.commit()
            if row:
                logger.info(f"Added dependency: {subtask_id} -> {depends_on_subtask_id}")
                return _row_to_dict(row)
            return None  # Already exists
        except Exception as e:
            conn.rollback()
            if "Circular dependency detected" in str(e):
                raise CycleError(str(e)) from e
            raise


def remove_dependency(subtask_id: str, depends_on_subtask_id: str) -> bool:
    """Remove a dependency.

    Args:
        subtask_id: The subtask that has the dependency
        depends_on_subtask_id: The dependency to remove

    Returns:
        True if deleted, False if not found
    """
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            DELETE FROM subtask_dependencies
            WHERE subtask_id = %s AND depends_on_subtask_id = %s
            """,
            (subtask_id, depends_on_subtask_id),
        )
        deleted = cur.rowcount > 0
        conn.commit()
        if deleted:
            logger.info(f"Removed dependency: {subtask_id} -> {depends_on_subtask_id}")
        return deleted


def get_dependencies(subtask_id: str) -> list[str]:
    """Get all subtasks that this subtask depends on.

    Args:
        subtask_id: The subtask to check

    Returns:
        List of subtask IDs that must complete before this one
    """
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT depends_on_subtask_id
            FROM subtask_dependencies
            WHERE subtask_id = %s
            """,
            (subtask_id,),
        )
        return [row[0] for row in cur.fetchall()]


def get_dependents(subtask_id: str) -> list[str]:
    """Get all subtasks that depend on this subtask.

    Args:
        subtask_id: The subtask to check

    Returns:
        List of subtask IDs that depend on this one completing
    """
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT subtask_id
            FROM subtask_dependencies
            WHERE depends_on_subtask_id = %s
            """,
            (subtask_id,),
        )
        return [row[0] for row in cur.fetchall()]


def get_blocking_dependencies(subtask_id: str) -> list[dict[str, Any]]:
    """Get incomplete dependencies that are blocking a subtask.

    Args:
        subtask_id: The subtask to check

    Returns:
        List of {subtask_id, passes} for blocking dependencies
    """
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT ts.id, ts.subtask_id, ts.passes
            FROM subtask_dependencies sd
            JOIN task_subtasks ts ON sd.depends_on_subtask_id = ts.id
            WHERE sd.subtask_id = %s AND ts.passes = FALSE
            """,
            (subtask_id,),
        )
        return [{"id": row[0], "subtask_id": row[1], "passes": row[2]} for row in cur.fetchall()]


def is_blocked(subtask_id: str) -> bool:
    """Check if a subtask is blocked by incomplete dependencies.

    Args:
        subtask_id: The subtask to check

    Returns:
        True if any dependency is incomplete
    """
    return len(get_blocking_dependencies(subtask_id)) > 0


def get_all_dependencies_for_task(task_id: str) -> list[dict[str, Any]]:
    """Get all dependency relationships for a task.

    Args:
        task_id: The task ID

    Returns:
        List of {subtask_id, depends_on_subtask_id} for all dependencies
    """
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT sd.id, sd.subtask_id, sd.depends_on_subtask_id, sd.created_at
            FROM subtask_dependencies sd
            JOIN task_subtasks ts ON sd.subtask_id = ts.id
            WHERE ts.task_id = %s
            """,
            (task_id,),
        )
        return [r for r in [_row_to_dict(row) for row in cur.fetchall()] if r is not None]


def bulk_add_dependencies(
    dependencies: list[tuple[str, str]],
) -> list[dict[str, Any]]:
    """Add multiple dependencies at once.

    Args:
        dependencies: List of (subtask_id, depends_on_subtask_id) tuples

    Returns:
        List of created dependency records (excludes duplicates)

    Raises:
        CycleError: If any dependency would create a cycle
    """
    if not dependencies:
        return []

    # Validate no self-references
    for subtask_id, depends_on in dependencies:
        if subtask_id == depends_on:
            raise ValueError(f"Subtask {subtask_id} cannot depend on itself")

    with get_connection() as conn:
        cur = conn.cursor()
        try:
            # Use executemany with ON CONFLICT
            cur.executemany(
                """
                INSERT INTO subtask_dependencies (subtask_id, depends_on_subtask_id)
                VALUES (%s, %s)
                ON CONFLICT (subtask_id, depends_on_subtask_id) DO NOTHING
                """,
                dependencies,
            )
            conn.commit()

            # Return what was actually inserted (query for them)
            if dependencies:
                placeholders = ", ".join("(%s, %s)" for _ in dependencies)
                flat_values = [v for pair in dependencies for v in pair]
                cur.execute(
                    f"""
                    SELECT * FROM subtask_dependencies
                    WHERE (subtask_id, depends_on_subtask_id) IN ({placeholders})
                    """,
                    flat_values,
                )
                return [r for r in [_row_to_dict(row) for row in cur.fetchall()] if r is not None]
            return []
        except Exception as e:
            conn.rollback()
            if "Circular dependency detected" in str(e):
                raise CycleError(str(e)) from e
            raise


def topological_sort(task_id: str) -> list[str]:
    """Get subtasks in execution order (dependencies first).

    Uses Kahn's algorithm for topological sorting.

    Args:
        task_id: The task ID

    Returns:
        List of subtask IDs in execution order

    Raises:
        CycleError: If a cycle is detected (shouldn't happen due to DB trigger)
    """
    with get_connection() as conn:
        cur = conn.cursor()

        # Get all subtasks for this task
        cur.execute(
            "SELECT id FROM task_subtasks WHERE task_id = %s ORDER BY display_order",
            (task_id,),
        )
        all_subtasks = [row[0] for row in cur.fetchall()]

        if not all_subtasks:
            return []

        # Get all dependencies
        cur.execute(
            """
            SELECT sd.subtask_id, sd.depends_on_subtask_id
            FROM subtask_dependencies sd
            JOIN task_subtasks ts ON sd.subtask_id = ts.id
            WHERE ts.task_id = %s
            """,
            (task_id,),
        )
        dependencies = cur.fetchall()

    # Build adjacency list and in-degree count
    in_degree: dict[str, int] = {s: 0 for s in all_subtasks}
    dependents: dict[str, list[str]] = {s: [] for s in all_subtasks}

    for subtask_id, depends_on in dependencies:
        if depends_on in in_degree:  # Only count valid dependencies
            in_degree[subtask_id] += 1
            dependents[depends_on].append(subtask_id)

    # Kahn's algorithm
    queue = [s for s in all_subtasks if in_degree[s] == 0]
    result = []

    while queue:
        # Sort queue by display_order for deterministic results
        current = queue.pop(0)
        result.append(current)

        for dependent in dependents[current]:
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                queue.append(dependent)

    if len(result) != len(all_subtasks):
        raise CycleError(
            f"Cycle detected in task {task_id}: "
            f"processed {len(result)}/{len(all_subtasks)} subtasks"
        )

    return result


def delete_dependencies_for_subtask(subtask_id: str) -> int:
    """Delete all dependencies involving a subtask.

    Removes both where subtask_id is the dependent AND where it's depended upon.

    Args:
        subtask_id: The subtask ID

    Returns:
        Number of dependencies deleted
    """
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            DELETE FROM subtask_dependencies
            WHERE subtask_id = %s OR depends_on_subtask_id = %s
            """,
            (subtask_id, subtask_id),
        )
        deleted = cur.rowcount
        conn.commit()
        if deleted:
            logger.info(f"Deleted {deleted} dependencies for subtask {subtask_id}")
        return deleted
