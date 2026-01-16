"""Subtasks storage layer - CRUD operations for task implementation subtasks.

This module provides data access for the task_subtasks table, which stores
normalized subtask data for structured task execution tracking.
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
# Note: steps column was dropped in migration 045 - steps are in task_subtask_steps table
# Note: details column added in migration 061 - stores rich implementation specs
SUBTASK_COLUMNS = """id, task_id, subtask_id, phase, description,
    details, passes, passed_at, display_order, created_at"""

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
        id, task_id, subtask_id, phase, description,
        details, passes, passed_at, display_order, created_at

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
        "details": row[5],  # Rich implementation spec from plan.json
        # Note: "steps" field is populated separately when include_steps=True
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
    steps: list[str | dict[str, Any]] | None = None,
    details: dict[str, Any] | None = None,
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
        details: Optional rich implementation spec from plan.json (deprecated)

    Returns:
        The created subtask dict.

    Raises:
        Exception: If task_id doesn't exist (FK constraint violation)
    """
    import json

    if steps is None:
        steps = []

    table_id = _generate_subtask_id(task_id, subtask_id)
    details_json = json.dumps(details) if details else None

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO task_subtasks (id, task_id, subtask_id, phase, description,
                                       details, display_order)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING {SUBTASK_COLUMNS}
            """,
            (
                table_id,
                task_id,
                subtask_id,
                phase,
                description,
                details_json,
                display_order,
            ),
        )
        row = cur.fetchone()
        conn.commit()

    result = _row_to_dict(row)

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

    subtasks = [_row_to_dict(row) for row in rows]

    if include_steps:
        from .steps import get_step_summary, get_steps_for_subtask

        for subtask in subtasks:
            subtask_table_id = subtask["id"]  # Already in table ID format
            subtask["steps_from_table"] = get_steps_for_subtask(subtask_table_id)
            subtask["step_summary"] = get_step_summary(subtask_table_id)

    return subtasks


class SubtaskGateError(Exception):
    """Raised when subtask completion gate is violated."""

    def __init__(self, message: str, incomplete_steps: list[int] | None = None):
        super().__init__(message)
        self.incomplete_steps = incomplete_steps or []


def update_subtask_passes(
    task_id: str,
    subtask_id: str,
    passes: bool,
    force: bool = False,
) -> dict[str, Any] | None:
    """Update subtask passes status with gate enforcement.

    When passes is set to True, also sets passed_at timestamp.
    When passes is set to False, clears passed_at.

    Gate enforcement: When setting passes=True, all steps for this subtask
    must have passes=True. This ensures all steps are verified complete.

    Args:
        task_id: Parent task ID
        subtask_id: Subtask ID (e.g., "1.1")
        passes: Whether the subtask passes
        force: If True, bypass the step completion gate check (use with caution)

    Returns:
        Updated subtask dict or None if not found.

    Raises:
        SubtaskGateError: If passes=True and not all steps are complete (unless force=True)
    """
    table_id = _generate_subtask_id(task_id, subtask_id)
    passed_at = datetime.now(UTC) if passes else None

    with get_connection() as conn, conn.cursor() as cur:
        # Gate check: if marking as passed, verify all steps are passed
        if passes and not force:
            cur.execute(
                """
                SELECT step_number FROM task_subtask_steps
                WHERE subtask_id = %s AND passes = FALSE
                ORDER BY step_number
                """,
                (table_id,),
            )
            incomplete = [row[0] for row in cur.fetchall()]
            if incomplete:
                msg = (
                    f"Cannot mark subtask {subtask_id} as passed: "
                    f"steps {incomplete} are not complete. "
                    f"Use force=True to bypass."
                )
                logger.warning(msg)
                raise SubtaskGateError(msg, incomplete_steps=incomplete)

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

    table_id = _generate_subtask_id(task_id, subtask_id)

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
            - details: dict (optional) - deprecated, use step-level specs

    Returns:
        List of created subtask dicts.

    Raises:
        Exception: If task_id doesn't exist or on DB error.
    """
    import json

    if not subtasks:
        return []

    created = []
    steps_to_create: list[tuple[str, list[str | dict[str, Any]]]] = []

    with get_connection() as conn, conn.cursor() as cur:
        for idx, subtask in enumerate(subtasks):
            subtask_id = subtask["subtask_id"]
            table_id = _generate_subtask_id(task_id, subtask_id)
            display_order = subtask.get("display_order", idx)
            steps = subtask.get("steps", [])
            details = subtask.get("details")
            details_json = json.dumps(details) if details else None

            cur.execute(
                f"""
                INSERT INTO task_subtasks (id, task_id, subtask_id, phase, description,
                                           details, display_order)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING {SUBTASK_COLUMNS}
                """,
                (
                    table_id,
                    task_id,
                    subtask_id,
                    subtask.get("phase"),
                    subtask["description"],
                    details_json,
                    display_order,
                ),
            )
            row = cur.fetchone()
            created.append(_row_to_dict(row))

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
