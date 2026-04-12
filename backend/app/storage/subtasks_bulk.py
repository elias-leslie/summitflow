"""Subtask bulk operations.

This module provides bulk creation operations for subtasks.
"""

from __future__ import annotations

from typing import Any

from ..logging_config import get_logger
from .connection import get_connection
from .subtasks_context import sync_subtasks_to_plan_context
from .subtasks_helpers import SUBTASK_COLUMNS, generate_subtask_id, row_to_dict

logger = get_logger(__name__)

_INSERT_SQL = f"""
    INSERT INTO task_subtasks (id, task_id, subtask_id, phase, description,
                               display_order, subtask_type)
    VALUES (%s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (task_id, subtask_id) DO UPDATE SET
        phase = EXCLUDED.phase,
        description = EXCLUDED.description,
        display_order = EXCLUDED.display_order,
        subtask_type = EXCLUDED.subtask_type
    RETURNING {SUBTASK_COLUMNS}
"""


def _insert_one_subtask(cur: Any, task_id: str, subtask: dict[str, Any], idx: int) -> dict[str, Any]:
    """Execute the INSERT for a single subtask row and return the row dict."""
    subtask_id = subtask["subtask_id"]
    table_id = generate_subtask_id(task_id, subtask_id)
    display_order = subtask.get("display_order", idx)

    cur.execute(
        _INSERT_SQL,
        (
            table_id,
            task_id,
            subtask_id,
            subtask.get("phase"),
            subtask["description"],
            display_order,
            subtask.get("subtask_type"),
        ),
    )
    row = cur.fetchone()
    return row_to_dict(row)


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
            - steps: Optional rich step guidance mirrored into task_spirit.context
            - depends_on: Optional dependency ids mirrored into task_spirit.context
            - display_order: int (optional, auto-assigned if missing)

    Returns:
        List of created subtask dicts.

    Raises:
        Exception: If task_id doesn't exist or on DB error.
    """
    if not subtasks:
        return []

    created: list[dict[str, Any]] = []
    with get_connection() as conn, conn.cursor() as cur:
        for idx, subtask in enumerate(subtasks):
            row_dict = _insert_one_subtask(cur, task_id, subtask, idx)
            created.append(row_dict)
        conn.commit()

    sync_subtasks_to_plan_context(task_id, subtasks)
    logger.info("Created %d subtasks for task %s", len(created), task_id)
    return created
