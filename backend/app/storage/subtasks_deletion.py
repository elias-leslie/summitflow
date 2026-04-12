"""Subtask deletion operations.

This module provides deletion operations for subtasks.
"""

from __future__ import annotations

from ..logging_config import get_logger
from .connection import get_connection
from .subtasks_context import remove_subtasks_from_plan_context
from .subtasks_helpers import generate_subtask_id

logger = get_logger(__name__)


def delete_subtasks_for_task(task_id: str) -> int:
    """Delete all subtasks for a task.

    Args:
        task_id: Parent task ID

    Returns:
        Number of subtasks deleted.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT subtask_id FROM task_subtasks WHERE task_id = %s", (task_id,))
        subtask_ids = [str(row[0]) for row in cur.fetchall()]
        cur.execute(
            "DELETE FROM task_subtasks WHERE task_id = %s",
            (task_id,),
        )
        count: int = cur.rowcount
        conn.commit()

    remove_subtasks_from_plan_context(task_id, subtask_ids)
    logger.debug("Deleted %d subtasks for task %s", count, task_id)
    return count


def delete_subtask(task_id: str, subtask_id: str) -> bool:
    """Delete a single subtask.

    Args:
        task_id: Parent task ID
        subtask_id: Subtask ID to delete (e.g., "99.1")

    Returns:
        True if subtask was deleted, False if not found.
    """
    table_id = generate_subtask_id(task_id, subtask_id)

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM task_subtasks WHERE id = %s",
            (table_id,),
        )
        deleted: bool = cur.rowcount > 0
        conn.commit()

    if deleted:
        remove_subtasks_from_plan_context(task_id, [subtask_id])
        logger.info("Deleted subtask %s from task %s", subtask_id, task_id)
    else:
        logger.warning("Subtask %s not found in task %s", subtask_id, task_id)

    return deleted
