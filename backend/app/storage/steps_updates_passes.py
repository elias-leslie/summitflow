"""Step pass status updates with mandatory verification."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from .connection import get_connection
from .steps_crud_serialization import STEP_COLUMNS, row_to_dict
from .steps_exceptions import StepVerificationError
from .steps_verification import _parse_expected, run_verify_command

logger = logging.getLogger(__name__)


def update_step_passes(
    subtask_id: str,
    step_number: int,
    passes: bool,
    project_root: str | None = None,
    *,
    already_verified: bool = False,
    project_id: str | None = None,
) -> dict[str, Any] | None:
    """Update step passes status with mandatory verification.

    When passes is set to True:
    1. Fetches the step's verify_command (required)
    2. Runs the verify_command with proper project venv
    3. Only marks step passes=true if verification passes (exit code 0)
    4. Raises StepVerificationError on failure or missing verify_command

    When already_verified is True, skips re-verification (caller already ran it).

    When passes is set to False, clears passed_at without verification.

    Args:
        subtask_id: Parent subtask ID
        step_number: Step number to update
        passes: Whether the step passes
        project_root: Working directory for verify_command execution.
                      If None, defaults to /home/kasadis/summitflow.
        already_verified: Skip re-running verify_command (caller already verified).
        project_id: Project ID for resolving venv paths in worktree contexts.

    Returns:
        Updated step dict or None if not found.

    Raises:
        StepVerificationError: If verification fails or verify_command is missing
    """
    # If marking as failed/incomplete, no verification needed
    if not passes:
        passed_at = None
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE task_subtask_steps
                SET passes = %s, passed_at = %s
                WHERE subtask_id = %s AND step_number = %s
                RETURNING {STEP_COLUMNS}
                """,
                (passes, passed_at, subtask_id, step_number),
            )
            row = cur.fetchone()
            conn.commit()

        if not row:
            logger.warning("Step %d not found for subtask %s", step_number, subtask_id)
            return None

        logger.debug("Updated step %d passes=False for subtask %s", step_number, subtask_id)
        return row_to_dict(row)

    if already_verified:
        passed_at = datetime.now(UTC)
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE task_subtask_steps
                SET passes = %s, passed_at = %s
                WHERE subtask_id = %s AND step_number = %s
                RETURNING {STEP_COLUMNS}
                """,
                (passes, passed_at, subtask_id, step_number),
            )
            row = cur.fetchone()
            conn.commit()
        if not row:
            logger.warning("Step %d not found for subtask %s", step_number, subtask_id)
            return None
        logger.info("Step %d passed for subtask %s (pre-verified)", step_number, subtask_id)
        return row_to_dict(row)

    # passes=True: Get the step to check for verify_command
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {STEP_COLUMNS}
            FROM task_subtask_steps
            WHERE subtask_id = %s AND step_number = %s
            """,
            (subtask_id, step_number),
        )
        row = cur.fetchone()

    if not row:
        logger.warning("Step %d not found for subtask %s", step_number, subtask_id)
        return None

    step = row_to_dict(row)
    verify_command = step.get("verify_command")
    expected_output = step.get("expected_output")

    # verify_command is required - fail if missing
    if not verify_command:
        raise StepVerificationError(
            message=f"Step {step_number} has no verify_command. Every step must have verification.",
            step_number=step_number,
            output="",
            exit_code=-1,
            verify_command=None,
            cwd=project_root,
        )

    # expected_output is required - fail if missing
    if not expected_output:
        raise StepVerificationError(
            message=f"Step {step_number} has no expected_output. Every step must define what success looks like.",
            step_number=step_number,
            output="",
            exit_code=-1,
            verify_command=verify_command,
            cwd=project_root,
        )

    # Parse expected output to determine check type
    check_type, check_value = _parse_expected(expected_output)

    # Run verification from project root
    status, exit_code, output = run_verify_command(
        verify_command, cwd=project_root, project_id=project_id,
    )

    if status != "passed":
        message = (
            f"Step {step_number} verification failed (exit code {exit_code}).\n"
            f"Command: {verify_command}\n"
            f"Expected: {expected_output}\n"
            f"Output: {output[:500]}"
        )

        raise StepVerificationError(
            message=message,
            step_number=step_number,
            output=output,
            exit_code=exit_code,
            verify_command=verify_command,
            cwd=project_root,
        )

    # For "exit_code" check type, exit code 0 is sufficient (already passed above)
    # For "contains" check type, verify the expected value appears in output
    if check_type == "contains" and check_value and check_value not in output:
        message = (
            f"Step {step_number} verification failed: expected output not found.\n"
            f"Command: {verify_command}\n"
            f"Expected: {expected_output}\n"
            f"Actual output: {output[:500]}"
        )

        raise StepVerificationError(
            message=message,
            step_number=step_number,
            output=output,
            exit_code=0,
            verify_command=verify_command,
            cwd=project_root,
        )

    logger.info("Step %d verify_command passed for subtask %s", step_number, subtask_id)

    # Verification passed - mark step as passed
    passed_at = datetime.now(UTC)

    with get_connection() as conn, conn.cursor() as cur:
        # Log incomplete previous steps for context (informational only)
        if step_number > 1:
            cur.execute(
                """
                SELECT step_number FROM task_subtask_steps
                WHERE subtask_id = %s AND step_number < %s AND passes = FALSE
                ORDER BY step_number
                """,
                (subtask_id, step_number),
            )
            incomplete = [row[0] for row in cur.fetchall()]
            if incomplete:
                logger.info(
                    f"Marking step {step_number} as passed with incomplete previous steps: {incomplete}"
                )

        cur.execute(
            f"""
            UPDATE task_subtask_steps
            SET passes = %s, passed_at = %s
            WHERE subtask_id = %s AND step_number = %s
            RETURNING {STEP_COLUMNS}
            """,
            (passes, passed_at, subtask_id, step_number),
        )
        row = cur.fetchone()
        conn.commit()

    if not row:
        logger.warning("Step %d not found for subtask %s", step_number, subtask_id)
        return None

    logger.info("Step %d passed for subtask %s (verified)", step_number, subtask_id)
    return row_to_dict(row)
