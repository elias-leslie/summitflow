"""Subtask creation - insert a single subtask.

This module handles the create_subtask operation, inserting a new subtask row.
"""

from __future__ import annotations

from ..logging_config import get_logger
from .connection import get_connection
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


def _attach_steps(result: dict[str, object], table_id: str, steps: list[str | dict[str, object]]) -> None:
    """Steps layer has been removed. No-op."""
    pass


def create_subtask(
    task_id: str,
    subtask_id: str,
    description: str,
    display_order: int,
    phase: str | None = None,
    steps: list[str | dict[str, object]] | None = None,
    subtask_type: str | None = None,
) -> dict[str, object]:
    """Create a new subtask, optionally with step rows.

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
    steps = steps or []
    table_id = generate_subtask_id(task_id, subtask_id)

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            _INSERT_SQL,
            (table_id, task_id, subtask_id, phase, description, display_order, subtask_type),
        )
        row = cur.fetchone()
        conn.commit()

    result = row_to_dict(row)

    if steps:
        _attach_steps(result, table_id, steps)

    logger.debug("Created subtask %s for task %s", subtask_id, task_id)
    return result
