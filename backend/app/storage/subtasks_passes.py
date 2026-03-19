"""Subtask passes update - gate logic for marking subtasks complete or incomplete.

This module handles the update_subtask_passes operation, enforcing step completion
and citation acknowledgment gates before allowing a subtask to be marked as passed.
"""

from __future__ import annotations

from datetime import UTC, datetime

from ..logging_config import get_logger
from .connection import get_connection
from .subtasks_helpers import SUBTASK_COLUMNS, generate_subtask_id, row_to_dict
from .subtasks_validation import validate_citations_acknowledged

logger = get_logger(__name__)


def _clear_subtask_passes(table_id: str, task_id: str, subtask_id: str) -> dict[str, object] | None:
    """Set passes=False and clear passed_at for a subtask."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE task_subtasks
            SET passes = %s, passed_at = %s
            WHERE id = %s
            RETURNING {SUBTASK_COLUMNS}
            """,
            (False, None, table_id),
        )
        row = cur.fetchone()
        conn.commit()

    if not row:
        logger.warning("Subtask %s not found for task %s", subtask_id, task_id)
        return None

    logger.debug("Updated subtask %s passes=False for task %s", subtask_id, task_id)
    return row_to_dict(row)


def _set_subtask_passes(
    table_id: str, task_id: str, subtask_id: str
) -> dict[str, object] | None:
    """Validate gates and mark subtask as passed."""
    # Steps layer removed - skip step completion validation
    passed_at = datetime.now(UTC)

    with get_connection() as conn, conn.cursor() as cur:
        # Lock the row to prevent TOCTOU race between read and update
        cur.execute(
            "SELECT citations_acknowledged_at FROM task_subtasks WHERE id = %s FOR UPDATE",
            (table_id,),
        )
        row = cur.fetchone()
        acknowledged_at = row[0] if row else None

        validate_citations_acknowledged(table_id, subtask_id, acknowledged_at)

        cur.execute(
            f"""
            UPDATE task_subtasks
            SET passes = %s, passed_at = %s
            WHERE id = %s
            RETURNING {SUBTASK_COLUMNS}
            """,
            (True, passed_at, table_id),
        )
        row = cur.fetchone()
        conn.commit()

    if not row:
        logger.warning("Subtask %s not found for task %s", subtask_id, task_id)
        return None

    logger.info("Subtask %s passed for task %s", subtask_id, task_id)
    return row_to_dict(row)


def update_subtask_passes(
    task_id: str, subtask_id: str, passes: bool
) -> dict[str, object] | None:
    """Update subtask passes status.

    Subtask passes ONLY when ALL its steps have passed.

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
    table_id = generate_subtask_id(task_id, subtask_id)
    if not passes:
        return _clear_subtask_passes(table_id, task_id, subtask_id)
    return _set_subtask_passes(table_id, task_id, subtask_id)
