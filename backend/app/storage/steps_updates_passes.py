"""Step pass status updates."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from .connection import get_connection
from .steps_crud_serialization import STEP_COLUMNS, row_to_dict

logger = logging.getLogger(__name__)

_TABLE = "task_subtask_steps"
_WHERE = "WHERE subtask_id = %s AND step_number = %s"
_UPDATE_SQL = f"UPDATE {_TABLE} SET passes = %s, passed_at = %s {_WHERE} RETURNING {STEP_COLUMNS}"


def _write_step_pass(
    subtask_id: str,
    step_number: int,
    passes: bool,
    passed_at: datetime | None,
    *,
    log_incomplete: bool = False,
) -> dict[str, object] | None:
    """Execute the DB update and return the updated step dict, or None."""
    with get_connection() as conn, conn.cursor() as cur:
        if log_incomplete and step_number > 1:
            cur.execute(
                f"SELECT step_number FROM {_TABLE} "
                "WHERE subtask_id = %s AND step_number < %s AND passes = FALSE ORDER BY step_number",
                (subtask_id, step_number),
            )
            incomplete = [row[0] for row in cur.fetchall()]
            if incomplete:
                logger.info(
                    "Marking step %d as passed with incomplete previous steps: %s",
                    step_number,
                    incomplete,
                )
        cur.execute(_UPDATE_SQL, (passes, passed_at, subtask_id, step_number))
        row = cur.fetchone()
        conn.commit()

    if not row:
        logger.warning("Step %d not found for subtask %s", step_number, subtask_id)
        return None
    return row_to_dict(row)


def update_step_passes(
    subtask_id: str,
    step_number: int,
    passes: bool,
    project_root: str | None = None,
    *,
    project_id: str | None = None,
) -> dict[str, object] | None:
    """Update step passes status.

    passes=True: marks step as passed with current timestamp.
    passes=False: clears passed_at.
    """
    if not passes:
        result = _write_step_pass(subtask_id, step_number, passes=False, passed_at=None)
        if result is not None:
            logger.debug("Updated step %d passes=False for subtask %s", step_number, subtask_id)
        return result

    result = _write_step_pass(
        subtask_id, step_number, passes=True, passed_at=datetime.now(UTC), log_incomplete=True
    )
    if result is not None:
        logger.info("Step %d passed for subtask %s", step_number, subtask_id)
    return result
