"""Subtask deletion operations.

This module provides deletion operations for subtasks.
"""

from __future__ import annotations

from ..logging_config import get_logger
from .connection import get_connection
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
