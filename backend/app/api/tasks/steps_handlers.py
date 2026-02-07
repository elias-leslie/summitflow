"""Request handlers for step status and pass updates.

This module contains handler functions that encapsulate the business logic
for updating step status and passes, including error handling.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from ...schemas.steps import StepResponse


def handle_update_step_status(
    table_id: str,
    step_number: int,
    request: dict[str, Any],
) -> StepResponse:
    """Handle step status update with validation and error handling.

    Args:
        table_id: Subtask table ID
        step_number: Step number to update
        request: Request dict with 'status' and optional 'fix_step_number'

    Returns:
        Updated step as StepResponse

    Raises:
        HTTPException: For validation errors or not found
    """
    from ...storage.steps import PlanDefectError
    from ...storage.steps import update_step_status as storage_update_step_status

    status = request.get("status")
    if not status:
        raise HTTPException(status_code=400, detail="status field is required")

    # For plan_defect, get fix_step_number (integer, not subtask ID)
    fix_step_number = request.get("fix_step_number")
    if fix_step_number is not None:
        try:
            fix_step_number = int(fix_step_number)
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=400,
                detail=f"fix_step_number must be an integer, got: {fix_step_number}",
            ) from None

    try:
        updated = storage_update_step_status(
            table_id, step_number, status, fix_step_number=fix_step_number
        )
    except PlanDefectError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from None

    if updated is None:
        raise HTTPException(
            status_code=404,
            detail=f"Step {step_number} not found",
        )

    return StepResponse(**updated)


def handle_update_step_passes(
    table_id: str,
    step_number: int,
    passes: bool,
    project_root: str | None = None,
    project_id: str | None = None,
) -> StepResponse:
    """Handle step passes update with verification and error handling.

    Args:
        table_id: Subtask table ID
        step_number: Step number to update
        passes: Whether the step passes
        project_root: Optional project root for verification
        project_id: Project ID for resolving venv in worktree contexts

    Returns:
        Updated step as StepResponse

    Raises:
        HTTPException: For validation/verification errors or not found
    """
    from ...storage.steps import StepGateError, StepVerificationError, update_step_passes

    try:
        updated = update_step_passes(
            table_id, step_number, passes,
            project_root=project_root, project_id=project_id,
        )
    except StepGateError as e:
        raise HTTPException(
            status_code=400,
            detail={
                "message": str(e),
                "missing_steps": e.missing_steps,
            },
        ) from e
    except StepVerificationError as e:
        raise HTTPException(
            status_code=422,
            detail={
                "message": str(e),
                "step_number": e.step_number,
                "output": e.output,
                "exit_code": e.exit_code,
                "verify_command": e.verify_command,
                "cwd": e.cwd,
                "verification_failed": True,
            },
        ) from e

    if updated is None:
        raise HTTPException(
            status_code=404,
            detail=f"Step {step_number} not found",
        )

    return StepResponse(**updated)


def handle_foreign_key_error(e: Exception, subtask_id: str, task_id: str) -> None:
    """Convert foreign key constraint errors to appropriate HTTP exceptions.

    Args:
        e: The exception to check
        subtask_id: Subtask ID for error message
        task_id: Task ID for error message

    Raises:
        HTTPException: 404 if foreign key constraint, 500 otherwise
    """
    error_msg = str(e)
    if "violates foreign key constraint" in error_msg.lower():
        raise HTTPException(
            status_code=404,
            detail=f"Subtask {subtask_id} not found for task {task_id}",
        ) from None
    raise HTTPException(status_code=500, detail=error_msg) from None
