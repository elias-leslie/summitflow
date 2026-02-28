"""Request handlers for step status and pass updates.

This module contains handler functions that encapsulate the business logic
for updating step status and passes, including error handling.
"""

from __future__ import annotations

from fastapi import HTTPException

from ...schemas.steps import StepResponse


def _parse_fix_step_number(raw: object) -> int | None:
    """Parse and validate fix_step_number from request value."""
    if raw is None:
        return None
    try:
        return int(str(raw))
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=400,
            detail=f"fix_step_number must be an integer, got: {raw}",
        ) from None


def _call_update_step_status(
    table_id: str, step_number: int, status: str, fix_step_number: int | None,
) -> dict[str, object] | None:
    """Call storage update_step_status and map exceptions to HTTPException."""
    from ...storage.steps import PlanDefectError
    from ...storage.steps import update_step_status as _update

    try:
        return _update(table_id, step_number, status, fix_step_number=fix_step_number)
    except (PlanDefectError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from None


def handle_update_step_status(
    table_id: str,
    step_number: int,
    request: dict[str, object],
) -> StepResponse:
    """Handle step status update with validation and error handling.

    Raises:
        HTTPException: 400 for validation errors, 404 if step not found.
    """
    status = request.get("status")
    if not status:
        raise HTTPException(status_code=400, detail="status field is required")
    fix_step_number = _parse_fix_step_number(request.get("fix_step_number"))
    updated = _call_update_step_status(table_id, step_number, str(status), fix_step_number)
    if updated is None:
        raise HTTPException(status_code=404, detail=f"Step {step_number} not found")
    return StepResponse(**updated)


def _raise_passes_error(e: Exception) -> None:
    """Raise HTTPException for StepGateError or StepVerificationError."""
    from ...storage.steps import StepGateError, StepVerificationError

    if isinstance(e, StepGateError):
        raise HTTPException(
            status_code=400,
            detail={"message": str(e), "missing_steps": e.missing_steps},
        ) from e
    if isinstance(e, StepVerificationError):
        raise HTTPException(
            status_code=422,
            detail={
                "message": str(e),
                "step_number": e.step_number,
                "output": e.output,
                "exit_code": e.exit_code,
                "cwd": e.cwd,
                "verification_failed": True,
            },
        ) from e
    raise e


def handle_update_step_passes(
    table_id: str,
    step_number: int,
    passes: bool,
    project_root: str | None = None,
    project_id: str | None = None,
) -> StepResponse:
    """Handle step passes update with error handling.

    Raises:
        HTTPException: 400/422 for gate/verification errors, 404 if not found.
    """
    from ...storage.steps import StepGateError, StepVerificationError, update_step_passes

    try:
        updated = update_step_passes(
            table_id, step_number, passes,
            project_root=project_root, project_id=project_id,
        )
    except (StepGateError, StepVerificationError) as e:
        _raise_passes_error(e)
        raise AssertionError("unreachable") from e

    if updated is None:
        raise HTTPException(status_code=404, detail=f"Step {step_number} not found")
    return StepResponse(**updated)


def handle_foreign_key_error(e: Exception, subtask_id: str, task_id: str) -> None:
    """Convert foreign key constraint errors to appropriate HTTP exceptions.

    Raises:
        HTTPException: 404 if foreign key constraint, 500 otherwise.
    """
    error_msg = str(e)
    if "violates foreign key constraint" in error_msg.lower():
        raise HTTPException(
            status_code=404,
            detail=f"Subtask {subtask_id} not found for task {task_id}",
        ) from None
    raise HTTPException(status_code=500, detail=error_msg) from None
