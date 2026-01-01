"""Subtasks storage layer - CRUD operations for task implementation subtasks.

This module provides data access for the task_subtasks table, which stores
normalized subtask data for structured task execution tracking.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from psycopg.rows import TupleRow

from .connection import get_connection

logger = logging.getLogger(__name__)

# Column list for all subtask SELECT/RETURNING queries (10 columns)
SUBTASK_COLUMNS = """id, task_id, subtask_id, phase, description, steps,
    passes, passed_at, display_order, created_at"""

# Expected column count for row validation
EXPECTED_SUBTASK_COLUMNS = 10


def _generate_subtask_id(task_id: str, subtask_id: str) -> str:
    """Generate a unique subtask table ID.

    Format: {task_id}-{subtask_id} e.g., "task-abc123-1.1"
    """
    return f"{task_id}-{subtask_id}"


def _row_to_dict(row: TupleRow | tuple[Any, ...] | None) -> dict[str, Any]:
    """Convert a database row to a subtask dict.

    Column order (10 columns):
        id, task_id, subtask_id, phase, description, steps,
        passes, passed_at, display_order, created_at
    """
    if row is None:
        raise ValueError("Row cannot be None")
    if len(row) != EXPECTED_SUBTASK_COLUMNS:
        raise ValueError(f"Expected {EXPECTED_SUBTASK_COLUMNS} columns, got {len(row)}")
    return {
        "id": row[0],
        "task_id": row[1],
        "subtask_id": row[2],
        "phase": row[3],
        "description": row[4],
        "steps": row[5] if row[5] else [],
        "passes": row[6],
        "passed_at": row[7].isoformat() if row[7] else None,
        "display_order": row[8],
        "created_at": row[9].isoformat() if row[9] else None,
    }


def create_subtask(
    task_id: str,
    subtask_id: str,
    description: str,
    display_order: int,
    phase: str | None = None,
    steps: list[str] | None = None,
) -> dict[str, Any]:
    """Create a new subtask.

    Args:
        task_id: Parent task ID (must exist in tasks table)
        subtask_id: Hierarchical ID like "1.1", "2.3"
        description: Subtask description
        display_order: Order for display (0-indexed)
        phase: Optional phase: research, database, backend, frontend, testing
        steps: Optional list of step strings

    Returns:
        The created subtask dict.

    Raises:
        Exception: If task_id doesn't exist (FK constraint violation)
    """
    if steps is None:
        steps = []

    table_id = _generate_subtask_id(task_id, subtask_id)

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO task_subtasks (id, task_id, subtask_id, phase, description,
                                       steps, display_order)
            VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s)
            RETURNING {SUBTASK_COLUMNS}
            """,
            (
                table_id,
                task_id,
                subtask_id,
                phase,
                description,
                json.dumps(steps),
                display_order,
            ),
        )
        row = cur.fetchone()
        conn.commit()

    logger.debug("Created subtask %s for task %s", subtask_id, task_id)
    return _row_to_dict(row)


def get_subtask(task_id: str, subtask_id: str) -> dict[str, Any] | None:
    """Get a single subtask by task_id and subtask_id.

    Returns:
        Subtask dict or None if not found.
    """
    table_id = _generate_subtask_id(task_id, subtask_id)

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {SUBTASK_COLUMNS}
            FROM task_subtasks
            WHERE id = %s
            """,
            (table_id,),
        )
        row = cur.fetchone()

    if not row:
        return None
    return _row_to_dict(row)


def get_subtasks_for_task(task_id: str) -> list[dict[str, Any]]:
    """Get all subtasks for a task, ordered by display_order.

    Args:
        task_id: Parent task ID

    Returns:
        List of subtask dicts, ordered by display_order.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {SUBTASK_COLUMNS}
            FROM task_subtasks
            WHERE task_id = %s
            ORDER BY display_order
            """,
            (task_id,),
        )
        rows = cur.fetchall()

    return [_row_to_dict(row) for row in rows]


def update_subtask_passes(
    task_id: str,
    subtask_id: str,
    passes: bool,
) -> dict[str, Any] | None:
    """Update subtask passes status.

    When passes is set to True, also sets passed_at timestamp.
    When passes is set to False, clears passed_at.

    Args:
        task_id: Parent task ID
        subtask_id: Subtask ID (e.g., "1.1")
        passes: Whether the subtask passes

    Returns:
        Updated subtask dict or None if not found.
    """
    table_id = _generate_subtask_id(task_id, subtask_id)
    passed_at = datetime.now(UTC) if passes else None

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE task_subtasks
            SET passes = %s, passed_at = %s
            WHERE id = %s
            RETURNING {SUBTASK_COLUMNS}
            """,
            (passes, passed_at, table_id),
        )
        row = cur.fetchone()
        conn.commit()

    if not row:
        logger.warning("Subtask %s not found for task %s", subtask_id, task_id)
        return None

    logger.debug("Updated subtask %s passes=%s for task %s", subtask_id, passes, task_id)
    return _row_to_dict(row)


def delete_subtasks_for_task(task_id: str) -> int:
    """Delete all subtasks for a task.

    Args:
        task_id: Parent task ID

    Returns:
        Number of subtasks deleted.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM task_subtasks WHERE task_id = %s",
            (task_id,),
        )
        count: int = cur.rowcount
        conn.commit()

    logger.debug("Deleted %d subtasks for task %s", count, task_id)
    return count


def bulk_create_subtasks(
    task_id: str,
    subtasks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Create multiple subtasks for a task in a single transaction.

    Args:
        task_id: Parent task ID
        subtasks: List of subtask dicts with keys:
            - subtask_id: str (required) - e.g., "1.1"
            - description: str (required)
            - phase: str (optional)
            - steps: list[str] (optional)
            - display_order: int (optional, auto-assigned if missing)

    Returns:
        List of created subtask dicts.

    Raises:
        Exception: If task_id doesn't exist or on DB error.
    """
    if not subtasks:
        return []

    created = []
    with get_connection() as conn, conn.cursor() as cur:
        for idx, subtask in enumerate(subtasks):
            subtask_id = subtask["subtask_id"]
            table_id = _generate_subtask_id(task_id, subtask_id)
            display_order = subtask.get("display_order", idx)
            steps = subtask.get("steps", [])

            cur.execute(
                f"""
                INSERT INTO task_subtasks (id, task_id, subtask_id, phase, description,
                                           steps, display_order)
                VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s)
                RETURNING {SUBTASK_COLUMNS}
                """,
                (
                    table_id,
                    task_id,
                    subtask_id,
                    subtask.get("phase"),
                    subtask["description"],
                    json.dumps(steps),
                    display_order,
                ),
            )
            row = cur.fetchone()
            created.append(_row_to_dict(row))

        conn.commit()

    logger.info("Created %d subtasks for task %s", len(created), task_id)
    return created


def get_subtask_summary(task_id: str) -> dict[str, Any]:
    """Get summary of subtask completion for a task.

    Returns:
        Dict with keys:
            - total: Total number of subtasks
            - completed: Number of subtasks with passes=True
            - next_subtask_id: ID of next incomplete subtask, or None
            - progress_percent: Completion percentage (0-100)
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE passes = TRUE) as completed,
                MIN(subtask_id) FILTER (WHERE passes = FALSE) as next_subtask_id
            FROM task_subtasks
            WHERE task_id = %s
            """,
            (task_id,),
        )
        row = cur.fetchone()

    total = row[0] if row else 0
    completed = row[1] if row else 0
    next_subtask_id = row[2] if row else None
    progress_percent = round((completed / total * 100) if total > 0 else 0, 1)

    return {
        "total": total,
        "completed": completed,
        "next_subtask_id": next_subtask_id,
        "progress_percent": progress_percent,
    }
