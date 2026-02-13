"""Step deletion with audit logging."""

from __future__ import annotations

import logging
from typing import Any

from .connection import get_connection
from .steps_crud import get_step
from .steps_exceptions import StepDeletionResult, StepGateError

logger = logging.getLogger(__name__)


def delete_step(
    subtask_id: str,
    step_number: int,
    *,
    force: bool = False,
    emit_event: bool = True,
) -> StepDeletionResult:
    """Delete a single step from a subtask with audit logging.

    IMPORTANT: Deleting passed steps invalidates the parent subtask's passes status.
    This is a safeguard against gaming the verification system by deleting steps
    that have already been verified.

    Args:
        subtask_id: Parent subtask ID (e.g., "task-abc123-1.1")
        step_number: Step number to delete
        force: If True, allow deletion of passed steps (required for passed steps)
        emit_event: If True, emit audit event for the deletion

    Returns:
        StepDeletionResult with deletion status and audit info.

    Raises:
        StepGateError: If trying to delete a passed step without force=True
    """
    # First, fetch the step to capture state before deletion
    step = get_step(subtask_id, step_number)
    if not step:
        logger.warning("Step %d not found in subtask %s", step_number, subtask_id)
        return StepDeletionResult(deleted=False)

    was_passed = step.get("passes", False)

    # Gate: Require force=True to delete passed steps
    if was_passed and not force:
        raise StepGateError(
            f"Step {step_number} has already passed verification. "
            "Deleting passed steps requires --force flag. "
            "This is a safeguard against gaming the verification system.",
            missing_steps=[step_number],
        )

    # Delete the step
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM task_subtask_steps WHERE subtask_id = %s AND step_number = %s",
            (subtask_id, step_number),
        )
        deleted: bool = cur.rowcount > 0
        conn.commit()

    if not deleted:
        logger.warning("Step %d not found in subtask %s (race condition?)", step_number, subtask_id)
        return StepDeletionResult(deleted=False)

    # If the deleted step was passed, invalidate the parent subtask's passes status
    subtask_invalidated = False
    if was_passed:
        subtask_invalidated = _invalidate_subtask_passes(subtask_id)

    # Emit audit event
    if emit_event:
        _emit_step_deletion_event(subtask_id, step_number, step, subtask_invalidated)

    logger.info(
        "Deleted step %d from subtask %s (was_passed=%s, subtask_invalidated=%s)",
        step_number,
        subtask_id,
        was_passed,
        subtask_invalidated,
    )

    return StepDeletionResult(
        deleted=True,
        was_passed=was_passed,
        subtask_invalidated=subtask_invalidated,
        step_details=step,
    )


def _invalidate_subtask_passes(subtask_id: str) -> bool:
    """Invalidate subtask.passes when a passed step is deleted.

    Args:
        subtask_id: Full subtask table ID (e.g., "task-abc123-1.1")

    Returns:
        True if subtask was invalidated, False if it wasn't passed or not found.
    """
    with get_connection() as conn, conn.cursor() as cur:
        # Only update if currently passed
        cur.execute(
            """
            UPDATE task_subtasks
            SET passes = FALSE, passed_at = NULL
            WHERE id = %s AND passes = TRUE
            RETURNING id
            """,
            (subtask_id,),
        )
        invalidated = cur.fetchone() is not None
        conn.commit()

    if invalidated:
        logger.warning(
            "Subtask %s passes status invalidated due to step deletion",
            subtask_id,
        )

    return invalidated


def _emit_step_deletion_event(
    subtask_id: str,
    step_number: int,
    step_details: dict[str, Any],
    subtask_invalidated: bool,
) -> None:
    """Emit audit event for step deletion.

    Args:
        subtask_id: Full subtask table ID
        step_number: Deleted step number
        step_details: Step state before deletion
        subtask_invalidated: Whether parent subtask was invalidated
    """
    from .events import EventLevel, log_task_event

    # Extract task_id from subtask_id (format: "task-abc123-1.1")
    # The task_id is everything before the last dash-separated segment
    parts = subtask_id.rsplit("-", 1)
    if len(parts) != 2:
        logger.warning("Cannot emit event: invalid subtask_id format %s", subtask_id)
        return

    task_id = parts[0]

    was_passed = step_details.get("passes", False)
    level: EventLevel = "warning" if was_passed else "info"

    message = f"Step {step_number} deleted from subtask {subtask_id}"
    if was_passed:
        message += " (WAS PASSED - verification bypassed)"
    if subtask_invalidated:
        message += " - subtask passes status invalidated"

    log_task_event(
        task_id=task_id,
        message=message,
        source="system",
        level=level,
        event_type="step_deletion",
        visibility="user",
        attributes={
            "subtask_id": subtask_id,
            "step_number": step_number,
            "was_passed": was_passed,
            "subtask_invalidated": subtask_invalidated,
            "verify_command": step_details.get("verify_command"),
            "description": step_details.get("description"),
        },
    )
