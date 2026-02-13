"""Subtask CRUD operations - Create, Read, Update, Delete for subtasks.

This module provides basic database operations for the task_subtasks table.
All functions use short subtask IDs (e.g., "1.1") and convert to table IDs internally.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from .connection import get_connection
from .steps import bulk_create_steps
from .subtasks_helpers import SUBTASK_COLUMNS, generate_subtask_id, row_to_dict

logger = logging.getLogger(__name__)


def create_subtask(
    task_id: str,
    subtask_id: str,
    description: str,
    display_order: int,
    phase: str | None = None,
    steps: list[str | dict[str, Any]] | None = None,
    subtask_type: str | None = None,
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
        subtask_type: Optional type for agent routing (backend, frontend, etc.)

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
                                       display_order, subtask_type)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (task_id, subtask_id) DO UPDATE SET
                phase = EXCLUDED.phase,
                description = EXCLUDED.description,
                display_order = EXCLUDED.display_order,
                subtask_type = EXCLUDED.subtask_type
            RETURNING {SUBTASK_COLUMNS}
            """,
            (table_id, task_id, subtask_id, phase, description, display_order, subtask_type),
        )
        row = cur.fetchone()
        conn.commit()

    result = row_to_dict(row)

    # Create steps in normalized table
    if steps:
        try:
            created_steps = bulk_create_steps(table_id, steps)
            result["steps"] = created_steps
        except ValueError:
            raise  # Validation errors (bad verify_command) must propagate
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
    task_id: str, include_steps: bool = False
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


def update_subtask_passes(
    task_id: str, subtask_id: str, passes: bool
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


# Re-export from other modules for backward compatibility
from .subtasks_bulk import bulk_create_subtasks  # noqa: E402
from .subtasks_deletion import delete_subtask, delete_subtasks_for_task  # noqa: E402

__all__ = [
    "bulk_create_subtasks",
    "create_subtask",
    "delete_subtask",
    "delete_subtasks_for_task",
    "generate_subtask_id",
    "get_subtask",
    "get_subtask_by_table_id",
    "get_subtasks_for_task",
    "update_subtask_passes",
]
