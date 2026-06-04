"""Subtask Dependencies storage - DAG operations for subtask execution order.

Handles the subtask_dependencies table (subtask A depends on subtask B).
Provides CRUD, topological sort, cycle detection, and blocking status checks.
"""

from __future__ import annotations

from typing import Any

from psycopg import sql

from ..logging_config import get_logger
from ._sql import static_sql
from ._subtask_dep_helpers import (
    DEP_SELECT,
    CycleError,
    fetch_inserted_deps,
    row_to_dict,
)
from .connection import get_connection

logger = get_logger(__name__)


def add_dependency(subtask_id: str, depends_on_subtask_id: str) -> dict[str, Any] | None:
    """Add a dependency. Returns the record or None if it already exists.

    Raises:
        CycleError: If this would create a cycle.
        ValueError: If subtask_id == depends_on_subtask_id.
    """
    if subtask_id == depends_on_subtask_id:
        raise ValueError("Subtask cannot depend on itself")

    with get_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                sql.SQL(
                    """
                INSERT INTO subtask_dependencies (subtask_id, depends_on_subtask_id)
                VALUES (%s, %s)
                ON CONFLICT (subtask_id, depends_on_subtask_id) DO NOTHING
                RETURNING {returning}
                """
                ).format(returning=static_sql(DEP_SELECT)),
                (subtask_id, depends_on_subtask_id),
            )
            row = cur.fetchone()
            conn.commit()
            if row:
                logger.info("Added dependency: %s -> %s", subtask_id, depends_on_subtask_id)
                return row_to_dict(row)
            return None
        except Exception as e:
            conn.rollback()
            if "Circular dependency detected" in str(e):
                raise CycleError(str(e)) from e
            raise


def remove_dependency(subtask_id: str, depends_on_subtask_id: str) -> bool:
    """Remove a dependency. Returns True if deleted, False if not found."""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM subtask_dependencies WHERE subtask_id = %s AND depends_on_subtask_id = %s",
            (subtask_id, depends_on_subtask_id),
        )
        deleted = cur.rowcount > 0
        conn.commit()
        if deleted:
            logger.info("Removed dependency: %s -> %s", subtask_id, depends_on_subtask_id)
        return deleted


def get_dependencies(subtask_id: str) -> list[str]:
    """Return subtask IDs that must complete before subtask_id."""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT depends_on_subtask_id FROM subtask_dependencies WHERE subtask_id = %s",
            (subtask_id,),
        )
        return [row[0] for row in cur.fetchall()]


def get_blocking_dependencies(subtask_id: str) -> list[dict[str, Any]]:
    """Return incomplete dependencies blocking subtask_id."""
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
        return [{"id": r[0], "subtask_id": r[1], "passes": r[2]} for r in cur.fetchall()]


def is_blocked(subtask_id: str) -> bool:
    """Return True if any dependency of subtask_id is incomplete."""
    return bool(get_blocking_dependencies(subtask_id))


def get_all_dependencies_for_task(task_id: str) -> list[dict[str, Any]]:
    """Return all dependency records for subtasks belonging to task_id."""
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
        return [r for row in cur.fetchall() if (r := row_to_dict(row)) is not None]


def bulk_add_dependencies(dependencies: list[tuple[str, str]]) -> list[dict[str, Any]]:
    """Add multiple dependencies at once. Returns inserted records.

    Raises:
        CycleError: If any dependency would create a cycle.
        ValueError: If any subtask depends on itself.
    """
    if not dependencies:
        return []
    for subtask_id, depends_on in dependencies:
        if subtask_id == depends_on:
            raise ValueError(f"Subtask {subtask_id} cannot depend on itself")
    with get_connection() as conn:
        cur = conn.cursor()
        try:
            cur.executemany(
                """
                INSERT INTO subtask_dependencies (subtask_id, depends_on_subtask_id)
                VALUES (%s, %s)
                ON CONFLICT (subtask_id, depends_on_subtask_id) DO NOTHING
                """,
                dependencies,
            )
            conn.commit()
            return fetch_inserted_deps(cur, dependencies)
        except Exception as e:
            conn.rollback()
            if "Circular dependency detected" in str(e):
                raise CycleError(str(e)) from e
            raise
