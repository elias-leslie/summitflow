"""Subtask CRUD operations - Create, Read, Update, Delete for subtasks.

This module provides basic database operations for the task_subtasks table.
All functions use short subtask IDs (e.g., "1.1") and convert to table IDs internally.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from psycopg.rows import TupleRow

from .connection import get_connection
from .steps import bulk_create_steps

logger = logging.getLogger(__name__)

# Column list for all subtask SELECT/RETURNING queries (10 columns)
SUBTASK_COLUMNS = """id, task_id, subtask_id, phase, description,
    passes, passed_at, display_order, created_at, citations_acknowledged_at"""

# Expected column count for row validation
EXPECTED_SUBTASK_COLUMNS = 10


def generate_subtask_id(task_id: str, subtask_id: str) -> str:
    """Generate a unique subtask table ID.

    Format: {task_id}-{subtask_id} e.g., "task-abc123-1.1"
    """
    return f"{task_id}-{subtask_id}"


def row_to_dict(row: TupleRow | tuple[Any, ...] | None) -> dict[str, Any]:
    """Convert a database row to a subtask dict.

    Column order (10 columns):
        id, task_id, subtask_id, phase, description,
        passes, passed_at, display_order, created_at, citations_acknowledged_at

    Note: steps field is always [] - steps are in task_subtask_steps table
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
        # Note: "steps" field is populated separately when include_steps=True
        "passes": row[5],
        "passed_at": row[6].isoformat() if row[6] else None,
        "display_order": row[7],
        "created_at": row[8].isoformat() if row[8] else None,
        "citations_acknowledged_at": row[9].isoformat() if row[9] else None,
    }


def create_subtask(
    task_id: str,
    subtask_id: str,
    description: str,
    display_order: int,
    phase: str | None = None,
    steps: list[str | dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Create a new subtask.

    Also creates step rows in task_subtask_steps table when steps are provided.
    The JSONB steps column is not used (deprecated).

    Args:
        task_id: Parent task ID (must exist in tasks table)
        subtask_id: Hierarchical ID like "1.1", "2.3"
        description: Subtask description
        display_order: Order for display (0-indexed)
        phase: Optional phase: research, database, backend, frontend, testing
        steps: Optional list of steps - strings or {description, spec} dicts

    Returns:
        The created subtask dict.

    Raises:
        Exception: If task_id doesn't exist (FK constraint violation)
    """
    if steps is None:
        steps = []

    table_id = generate_subtask_id(task_id, subtask_id)

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO task_subtasks (id, task_id, subtask_id, phase, description,
                                       display_order)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (task_id, subtask_id) DO UPDATE SET
                phase = EXCLUDED.phase,
                description = EXCLUDED.description,
                display_order = EXCLUDED.display_order
            RETURNING {SUBTASK_COLUMNS}
            """,
            (
                table_id,
                task_id,
                subtask_id,
                phase,
                description,
                display_order,
            ),
        )
        row = cur.fetchone()
        conn.commit()

    result = row_to_dict(row)

    # Create steps in normalized table
    if steps:
        try:
            created_steps = bulk_create_steps(table_id, steps)
            result["steps"] = created_steps
        except Exception as e:
            logger.error("Failed to create steps for subtask %s: %s", table_id, e)
            # Continue - subtask created, steps failed (partial success)

    logger.debug("Created subtask %s for task %s", subtask_id, task_id)
    return result


def get_subtask(task_id: str, subtask_id: str) -> dict[str, Any] | None:
    """Get a single subtask by task_id and subtask_id.

    Returns:
        Subtask dict or None if not found.
    """
    table_id = generate_subtask_id(task_id, subtask_id)

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
    return row_to_dict(row)


def get_subtask_by_table_id(table_id: str) -> dict[str, Any] | None:
    """Get a single subtask by its full table ID.

    Args:
        table_id: Full subtask ID (e.g., "task-abc123-1.1")

    Returns:
        Subtask dict or None if not found.
    """
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
    return row_to_dict(row)


def get_subtasks_for_task(
    task_id: str,
    include_steps: bool = False,
) -> list[dict[str, Any]]:
    """Get all subtasks for a task, ordered by display_order.

    Args:
        task_id: Parent task ID
        include_steps: If True, include steps from task_subtask_steps table

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

    subtasks = [row_to_dict(row) for row in rows]

    if include_steps:
        from .steps import get_step_summary, get_steps_for_subtask

        for subtask in subtasks:
            subtask_table_id = subtask["id"]  # Already in table ID format
            subtask["steps_from_table"] = get_steps_for_subtask(subtask_table_id)
            subtask["step_summary"] = get_step_summary(subtask_table_id)

    return subtasks


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


def delete_subtask(task_id: str, subtask_id: str) -> bool:
    """Delete a single subtask and its steps.

    Cascading delete: Steps are deleted first (FK constraint), then the subtask.

    Args:
        task_id: Parent task ID
        subtask_id: Subtask ID to delete (e.g., "99.1")

    Returns:
        True if subtask was deleted, False if not found.
    """
    from .steps import delete_steps_for_subtask

    table_id = generate_subtask_id(task_id, subtask_id)

    # First delete associated steps (FK cascade not configured)
    steps_deleted = delete_steps_for_subtask(table_id)

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM task_subtasks WHERE id = %s",
            (table_id,),
        )
        deleted: bool = cur.rowcount > 0
        conn.commit()

    if deleted:
        logger.info(
            "Deleted subtask %s from task %s (%d steps removed)",
            subtask_id,
            task_id,
            steps_deleted,
        )
    else:
        logger.warning("Subtask %s not found in task %s", subtask_id, task_id)

    return deleted


def bulk_create_subtasks(
    task_id: str,
    subtasks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Create multiple subtasks for a task in a single transaction.

    Also creates step rows in task_subtask_steps table when steps are provided.
    The JSONB steps column is not used (deprecated).

    Args:
        task_id: Parent task ID
        subtasks: List of subtask dicts with keys:
            - subtask_id: str (required) - e.g., "1.1"
            - description: str (required)
            - phase: str (optional)
            - steps: list[str | dict] (optional) - strings or {description, spec} objects
            - display_order: int (optional, auto-assigned if missing)

    Returns:
        List of created subtask dicts.

    Raises:
        Exception: If task_id doesn't exist or on DB error.
    """
    if not subtasks:
        return []

    created = []
    steps_to_create: list[tuple[str, list[str | dict[str, Any]]]] = []

    with get_connection() as conn, conn.cursor() as cur:
        for idx, subtask in enumerate(subtasks):
            subtask_id = subtask["subtask_id"]
            table_id = generate_subtask_id(task_id, subtask_id)
            display_order = subtask.get("display_order", idx)
            steps = subtask.get("steps", [])

            cur.execute(
                f"""
                INSERT INTO task_subtasks (id, task_id, subtask_id, phase, description,
                                           display_order)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (task_id, subtask_id) DO UPDATE SET
                    phase = EXCLUDED.phase,
                    description = EXCLUDED.description,
                    display_order = EXCLUDED.display_order
                RETURNING {SUBTASK_COLUMNS}
                """,
                (
                    table_id,
                    task_id,
                    subtask_id,
                    subtask.get("phase"),
                    subtask["description"],
                    display_order,
                ),
            )
            row = cur.fetchone()
            created.append(row_to_dict(row))

            # Queue steps for creation after subtask commit
            if steps:
                steps_to_create.append((table_id, steps))

        conn.commit()

    # Create steps in normalized table (outside subtask transaction for safety)
    # Track which subtasks got steps so we can update the response
    subtasks_with_steps: dict[str, list[dict[str, Any]]] = {}
    for subtask_table_id, step_items in steps_to_create:
        try:
            created_steps = bulk_create_steps(subtask_table_id, step_items)
            subtasks_with_steps[subtask_table_id] = created_steps
        except Exception as e:
            logger.error("Failed to create steps for subtask %s: %s", subtask_table_id, e)
            # Continue - subtask created, steps failed (partial success)

    # Update returned subtasks with their created steps
    for subtask in created:
        subtask_table_id = subtask["id"]
        if subtask_table_id in subtasks_with_steps:
            subtask["steps_from_table"] = subtasks_with_steps[subtask_table_id]

    logger.info("Created %d subtasks for task %s", len(created), task_id)
    return created


def update_subtask_passes(
    task_id: str,
    subtask_id: str,
    passes: bool,
) -> dict[str, Any] | None:
    """Update subtask passes status.

    Verification happens at the step level (via step.verify_command).
    Subtask passes ONLY when ALL its steps have passed verification.

    When passes is set to True:
    1. Checks that all steps are passed (required, no bypass)
    2. Raises SubtaskGateError if any step is incomplete
    3. Marks subtask as passed only if all steps passed

    When passes is set to False, clears passed_at.

    Args:
        task_id: Parent task ID
        subtask_id: Subtask ID (e.g., "1.1")
        passes: Whether the subtask passes

    Returns:
        Updated subtask dict or None if not found.

    Raises:
        SubtaskGateError: If any steps are incomplete (no bypass available)
    """
    from .subtasks_validation import (
        validate_citations_acknowledged,
        validate_steps_complete,
    )

    table_id = generate_subtask_id(task_id, subtask_id)

    # If marking as failed/incomplete, just update
    if not passes:
        passed_at = None
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

        logger.debug("Updated subtask %s passes=False for task %s", subtask_id, task_id)
        return row_to_dict(row)

    # passes=True: Gate on all steps being complete (no bypass)
    from .steps import get_steps_for_subtask

    steps = get_steps_for_subtask(table_id)
    validate_steps_complete(subtask_id, steps)

    # Gate: Must acknowledge memory usage before subtask can pass
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT citations_acknowledged_at FROM task_subtasks WHERE id = %s",
            (table_id,),
        )
        row = cur.fetchone()
        acknowledged_at = row[0] if row else None

    validate_citations_acknowledged(table_id, subtask_id, acknowledged_at)

    # All steps passed and citations acknowledged - mark subtask as passed
    passed_at = datetime.now(UTC)

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

    logger.info("Subtask %s passed for task %s", subtask_id, task_id)
    return row_to_dict(row)


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
