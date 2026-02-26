"""Step status updates with plan defect handling."""

from __future__ import annotations

import logging

from .connection import get_connection
from .steps_constants import STEP_STATUS_PLAN_DEFECT, VALID_STEP_STATUSES
from .steps_crud import get_step
from .steps_crud_serialization import STEP_COLUMNS, row_to_dict
from .steps_exceptions import PlanDefectError

logger = logging.getLogger(__name__)


def _validate_status(status: str) -> None:
    """Raise ValueError if status is not a recognised value."""
    if status not in VALID_STEP_STATUSES:
        raise ValueError(
            f"Invalid status '{status}'. Valid values: {', '.join(sorted(VALID_STEP_STATUSES))}"
        )


def _validate_fix_step_numbers(step_number: int, fix_step_number: int | None) -> None:
    """Raise PlanDefectError when fix_step_number is absent or equals step_number."""
    if fix_step_number is None:
        raise PlanDefectError(
            "plan_defect status requires a fix_step_number. "
            "Add a new step with correct verification, pass it, "
            "then mark this step as plan_defect."
        )
    if fix_step_number == step_number:
        raise PlanDefectError(
            f"Fix step cannot be the same as the defective step ({step_number}). "
            "Add a new step with correct verification."
        )


def _validate_fix_step_exists_and_passed(
    subtask_id: str, fix_step_number: int
) -> None:
    """Raise PlanDefectError when the fix step is missing or has not passed."""
    fix_step = get_step(subtask_id, fix_step_number)
    if not fix_step:
        raise PlanDefectError(
            f"Fix step {fix_step_number} not found in subtask. "
            "Add the fix step first: st step add <subtask> 'Fix: correct verification'"
        )
    if not fix_step.get("passes"):
        raise PlanDefectError(
            f"Fix step {fix_step_number} has not passed verification. "
            "Pass the fix step first: st step pass <subtask> {fix_step_number}"
        )


def _validate_plan_defect(
    subtask_id: str,
    step_number: int,
    fix_step_number: int | None,
) -> None:
    """Validate all requirements for a plan_defect status update."""
    _validate_fix_step_numbers(step_number, fix_step_number)
    # _validate_fix_step_numbers raises if fix_step_number is None, so it is
    # guaranteed to be an int at this point.
    assert fix_step_number is not None
    _validate_fix_step_exists_and_passed(subtask_id, fix_step_number)
    logger.info(
        "Step %d marked as plan_defect with fix step %d",
        step_number,
        fix_step_number,
    )


def _execute_status_update(
    subtask_id: str,
    step_number: int,
    status: str,
    fix_step_number: int | None,
) -> dict[str, object] | None:
    """Persist the status change and return the updated row, or None if not found."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE task_subtask_steps
            SET status = %s, fix_step_number = %s
            WHERE subtask_id = %s AND step_number = %s
            RETURNING {STEP_COLUMNS}
            """,
            (status, fix_step_number, subtask_id, step_number),
        )
        row = cur.fetchone()
        conn.commit()

    if not row:
        logger.warning("Step %d not found for subtask %s", step_number, subtask_id)
        return None

    logger.info("Updated step %d status to '%s' for subtask %s", step_number, status, subtask_id)
    return row_to_dict(row)


def update_step_status(
    subtask_id: str,
    step_number: int,
    status: str,
    fix_step_number: int | None = None,
) -> dict[str, object] | None:
    """Update step status.

    Valid status values:
    - 'pending': Step not yet attempted
    - 'passed': Step completed successfully
    - 'failed': Step failed verification
    - 'plan_defect': Step's verification was wrong (plan issue, not implementation)

    For 'plan_defect' status, a fix_step_number is REQUIRED. The fix step must:
    1. Be a different step within the same subtask
    2. Have passes=True (correct verification that proves implementation works)

    Args:
        subtask_id: Parent subtask ID
        step_number: Step number to update
        status: New status value
        fix_step_number: For plan_defect only: step number with correct verification

    Returns:
        Updated step dict or None if not found.

    Raises:
        ValueError: If status is not a valid value
        PlanDefectError: If plan_defect without valid completed fix step
    """
    _validate_status(status)

    if status == STEP_STATUS_PLAN_DEFECT:
        _validate_plan_defect(subtask_id, step_number, fix_step_number)

    return _execute_status_update(subtask_id, step_number, status, fix_step_number)
