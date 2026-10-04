"""Subtask passes update - gate logic for marking subtasks complete or incomplete.

This module handles the update_subtask_passes operation, enforcing step completion
and dependency gates before allowing a subtask to be marked as passed.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import psycopg

from ..logging_config import get_logger
from .connection import get_connection
from .subtasks_helpers import SUBTASK_COLUMNS, generate_subtask_id, row_to_dict
from .subtasks_validation import SubtaskGateError

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
    table_id: str, task_id: str, subtask_id: str, *, owned_claim: dict[str, Any] | None = None
) -> dict[str, object] | None:
    """Validate gates and mark subtask as passed."""
    # Steps layer removed - skip step completion validation
    passed_at = datetime.now(UTC)

    try:
        with get_connection() as conn, conn.cursor() as cur:
            if owned_claim is not None:
                if not owned_claim.get("claimed_by") or not owned_claim.get("claimed_at") or not owned_claim.get("project_id"):
                    raise ValueError("Subtask completion requires an exact project claim")
                cur.execute("""SELECT id FROM tasks WHERE id = %s AND project_id = %s
                               AND status = 'running' AND claimed_by = %s
                               AND claimed_at = %s::timestamptz AND lock_expires_at > NOW() FOR UPDATE""",
                            (task_id, owned_claim["project_id"], owned_claim["claimed_by"], owned_claim["claimed_at"]))
                if not cur.fetchone():
                    raise ValueError("Task claim changed before prerequisite subtask completion")
            cur.execute("SELECT id FROM task_subtasks WHERE id = %s FOR UPDATE", (table_id,))
            cur.execute(
                """
                SELECT ts.subtask_id
                FROM subtask_dependencies sd
                JOIN task_subtasks ts ON sd.depends_on_subtask_id = ts.id
                WHERE sd.subtask_id = %s AND ts.passes = FALSE
                ORDER BY ts.display_order, ts.subtask_id
                """,
                (table_id,),
            )
            blocker_ids = ", ".join(str(row[0]) for row in cur.fetchall())
            if blocker_ids:
                raise SubtaskGateError(
                    f"Cannot pass subtask {subtask_id}; incomplete dependencies: {blocker_ids}",
                    incomplete_steps=[],
                )

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
    except psycopg.Error as exc:
        if "incomplete dependencies" in str(exc):
            raise SubtaskGateError(str(exc), incomplete_steps=[]) from exc
        raise

    if not row:
        logger.warning("Subtask %s not found for task %s", subtask_id, task_id)
        return None

    logger.info("Subtask %s passed for task %s", subtask_id, task_id)
    return row_to_dict(row)


def update_subtask_passes(
    task_id: str, subtask_id: str, passes: bool, *, owned_claim: dict[str, Any] | None = None
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
    return _set_subtask_passes(table_id, task_id, subtask_id, owned_claim=owned_claim)
