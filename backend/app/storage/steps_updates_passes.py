"""Step pass status updates with mandatory verification."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from .connection import get_connection
from .steps_crud_serialization import STEP_COLUMNS, row_to_dict
from .steps_exceptions import StepVerificationError
from .steps_verification import run_verify_command

logger = logging.getLogger(__name__)

_TABLE = "task_subtask_steps"
_WHERE = "WHERE subtask_id = %s AND step_number = %s"
_UPDATE_SQL = f"UPDATE {_TABLE} SET passes = %s, passed_at = %s {_WHERE} RETURNING {STEP_COLUMNS}"
_SELECT_SQL = f"SELECT {STEP_COLUMNS} FROM {_TABLE} {_WHERE}"
_INCOMPLETE_SQL = (
    f"SELECT step_number FROM {_TABLE} "
    "WHERE subtask_id = %s AND step_number < %s AND passes = FALSE ORDER BY step_number"
)


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
            cur.execute(_INCOMPLETE_SQL, (subtask_id, step_number))
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


def _verify_and_pass_step(
    subtask_id: str,
    step_number: int,
    project_root: str | None,
    project_id: str | None,
) -> dict[str, object] | None:
    """Fetch step, run verify_command, mark passed on success."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(_SELECT_SQL, (subtask_id, step_number))
        row = cur.fetchone()

    if not row:
        logger.warning("Step %d not found for subtask %s", step_number, subtask_id)
        return None

    step = row_to_dict(row)
    verify_command = step.get("verify_command")

    if not verify_command:
        raise StepVerificationError(
            message=f"Step {step_number} has no verify_command.",
            step_number=step_number,
            output="",
            exit_code=-1,
            verify_command=None,
            cwd=project_root,
        )

    status, exit_code, output = run_verify_command(verify_command, cwd=project_root, project_id=project_id)

    if status != "passed":
        raise StepVerificationError(
            message=f"Step {step_number} verification failed (exit code {exit_code}).\nCommand: {verify_command}\nOutput: {output[:500]}",
            step_number=step_number,
            output=output,
            exit_code=exit_code,
            verify_command=verify_command,
            cwd=project_root,
        )

    logger.info("Step %d verify_command passed for subtask %s", step_number, subtask_id)
    result = _write_step_pass(subtask_id, step_number, passes=True, passed_at=datetime.now(UTC), log_incomplete=True)
    if result is not None:
        logger.info("Step %d passed for subtask %s (verified)", step_number, subtask_id)
    return result


def update_step_passes(
    subtask_id: str,
    step_number: int,
    passes: bool,
    project_root: str | None = None,
    *,
    already_verified: bool = False,
    project_id: str | None = None,
) -> dict[str, object] | None:
    """Update step passes status with mandatory verification.

    passes=True: fetches verify_command, runs it, marks passed only on exit 0.
    already_verified=True: skips re-running verification (caller already ran it).
    passes=False: clears passed_at without verification.

    Raises StepVerificationError if verification fails or verify_command is missing.
    """
    if not passes:
        result = _write_step_pass(subtask_id, step_number, passes=False, passed_at=None)
        if result is not None:
            logger.debug("Updated step %d passes=False for subtask %s", step_number, subtask_id)
        return result

    if already_verified:
        result = _write_step_pass(
            subtask_id, step_number, passes=True, passed_at=datetime.now(UTC)
        )
        if result is not None:
            logger.info("Step %d passed for subtask %s (pre-verified)", step_number, subtask_id)
        return result

    return _verify_and_pass_step(subtask_id, step_number, project_root, project_id)
