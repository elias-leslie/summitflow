"""Subtask CRUD operations - Create, Read, Update, Delete for subtasks.

This module provides basic database operations for the task_subtasks table.
All functions use short subtask IDs (e.g., "1.1") and convert to table IDs internally.
"""

from __future__ import annotations

import logging

from .connection import get_connection
from .subtasks_helpers import SUBTASK_COLUMNS, generate_subtask_id, row_to_dict

logger = logging.getLogger(__name__)


def get_subtask(task_id: str, subtask_id: str) -> dict[str, object] | None:
    """Get a single subtask by task_id and subtask_id.

    Returns:
        Subtask dict or None if not found.
    """
    table_id = generate_subtask_id(task_id, subtask_id)

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT {SUBTASK_COLUMNS} FROM task_subtasks WHERE id = %s",
            (table_id,),
        )
        row = cur.fetchone()

    if not row:
        return None
    return row_to_dict(row)


def get_subtask_by_table_id(table_id: str) -> dict[str, object] | None:
    """Get a single subtask by its full table ID.

    Args:
        table_id: Full subtask ID (e.g., "task-abc123-1.1")

    Returns:
        Subtask dict or None if not found.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT {SUBTASK_COLUMNS} FROM task_subtasks WHERE id = %s",
            (table_id,),
        )
        row = cur.fetchone()

    if not row:
        return None
    return row_to_dict(row)


def get_subtasks_for_task(
    task_id: str, include_steps: bool = False
) -> list[dict[str, object]]:
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
            subtask_table_id = str(subtask["id"])
            subtask["steps_from_table"] = get_steps_for_subtask(subtask_table_id)
            subtask["step_summary"] = get_step_summary(subtask_table_id)

    return subtasks


# Re-export from focused modules for backward compatibility
from .subtasks_bulk import bulk_create_subtasks  # noqa: E402
from .subtasks_create import create_subtask  # noqa: E402
from .subtasks_deletion import delete_subtask, delete_subtasks_for_task  # noqa: E402
from .subtasks_passes import update_subtask_passes  # noqa: E402

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
