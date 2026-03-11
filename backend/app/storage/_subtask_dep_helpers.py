"""Helper utilities for subtask_dependencies storage module.

Shared types, row conversion, DB query helpers, and topological sort logic.
"""

from __future__ import annotations

from collections import deque
from typing import Any

from psycopg.rows import TupleRow

from .connection import get_connection

# Explicit column list for SELECT queries
DEP_COLUMNS = ("id", "subtask_id", "depends_on_subtask_id", "created_at")
DEP_SELECT = ", ".join(DEP_COLUMNS)
EXPECTED_COLUMNS = len(DEP_COLUMNS)


class CycleError(Exception):
    """Raised when adding a dependency would create a cycle."""

    def __init__(self, message: str, cycle_path: list[str] | None = None):
        super().__init__(message)
        self.cycle_path = cycle_path or []


def row_to_dict(row: TupleRow | tuple[Any, ...] | None) -> dict[str, Any] | None:
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


def fetch_task_subtasks_and_deps(task_id: str) -> tuple[list[str], list[tuple[str, str]]]:
    """Fetch all subtask IDs and their dependency pairs for a task.

    Returns:
        Tuple of (all_subtask_ids, dependency_pairs)
    """
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM task_subtasks WHERE task_id = %s ORDER BY display_order",
            (task_id,),
        )
        all_subtasks = [row[0] for row in cur.fetchall()]

        if not all_subtasks:
            return [], []

        cur.execute(
            """
            SELECT sd.subtask_id, sd.depends_on_subtask_id
            FROM subtask_dependencies sd
            JOIN task_subtasks ts ON sd.subtask_id = ts.id
            WHERE ts.task_id = %s
            """,
            (task_id,),
        )
        deps: list[tuple[str, str]] = cur.fetchall()

    return all_subtasks, deps


def build_graph(
    all_subtasks: list[str],
    dependencies: list[tuple[str, str]],
) -> tuple[dict[str, int], dict[str, list[str]]]:
    """Build in-degree and adjacency structures for topological sort."""
    in_degree: dict[str, int] = {s: 0 for s in all_subtasks}
    dependents: dict[str, list[str]] = {s: [] for s in all_subtasks}

    for subtask_id, depends_on in dependencies:
        if depends_on in in_degree:
            in_degree[subtask_id] += 1
            dependents[depends_on].append(subtask_id)

    return in_degree, dependents


def kahn_sort(
    all_subtasks: list[str],
    in_degree: dict[str, int],
    dependents: dict[str, list[str]],
    task_id: str,
) -> list[str]:
    """Run Kahn's topological sort algorithm.

    Raises:
        CycleError: If a cycle is detected
    """
    queue = deque(s for s in all_subtasks if in_degree[s] == 0)
    result: list[str] = []

    while queue:
        current = queue.popleft()
        result.append(current)
        for dep in dependents[current]:
            in_degree[dep] -= 1
            if in_degree[dep] == 0:
                queue.append(dep)

    if len(result) != len(all_subtasks):
        # Nodes still blocked (involved in or downstream of cycle)
        blocked_nodes = [s for s in all_subtasks if in_degree[s] > 0]
        raise CycleError(
            f"Cycle detected in task {task_id}: "
            f"processed {len(result)}/{len(all_subtasks)} subtasks",
            cycle_path=blocked_nodes
        )

    return result


def fetch_inserted_deps(cur: Any, dependencies: list[tuple[str, str]]) -> list[dict[str, Any]]:
    """Fetch dependency records matching the given (subtask_id, depends_on) pairs."""
    if not dependencies:
        return []
    placeholders = ", ".join("(%s, %s)" for _ in dependencies)
    flat_values = [v for pair in dependencies for v in pair]
    cur.execute(
        f"SELECT {DEP_SELECT} FROM subtask_dependencies"
        f" WHERE (subtask_id, depends_on_subtask_id) IN ({placeholders})",
        flat_values,
    )
    return [r for r in [row_to_dict(row) for row in cur.fetchall()] if r is not None]
