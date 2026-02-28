"""Individual step write handler implementations.

This module contains handlers for creating, updating, and deleting single steps.
"""

from __future__ import annotations

from fastapi import HTTPException

from ...schemas.steps import (
    StepCreateWithVerification,
    StepFieldsUpdate,
    StepInsert,
    StepResponse,
)
from .steps_handlers import handle_foreign_key_error


def insert_step_handler(
    table_id: str,
    position: int,
    request: StepInsert,
    subtask_id: str,
    task_id: str,
) -> StepResponse:
    """Insert a step at a specific position."""
    from ...storage.steps import insert_step

    try:
        created = insert_step(
            table_id,
            position,
            request.description,
            request.spec,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    except Exception as e:
        handle_foreign_key_error(e, subtask_id, task_id)
    return StepResponse(**created)


def create_with_verification_handler(
    table_id: str,
    request: StepCreateWithVerification,
    subtask_id: str,
    task_id: str,
) -> StepResponse:
    """Create a step with verification."""
    from ...storage.steps import create_step, get_steps_for_subtask

    existing_steps = get_steps_for_subtask(table_id)
    next_number = max((s["step_number"] for s in existing_steps), default=0) + 1
    try:
        created = create_step(
            subtask_id=table_id,
            step_number=next_number,
            description=request.description,
            spec=request.spec,
            verify_command=request.verify_command,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    except Exception as e:
        handle_foreign_key_error(e, subtask_id, task_id)
    return StepResponse(**created)


def update_fields_handler(
    table_id: str,
    step_number: int,
    request: StepFieldsUpdate,
    subtask_id: str,
) -> StepResponse:
    """Update step fields."""
    from ...storage.steps import update_step_fields as storage_update_step_fields

    try:
        updated = storage_update_step_fields(
            subtask_id=table_id,
            step_number=step_number,
            description=request.description,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from None
    if updated is None:
        raise HTTPException(
            status_code=404,
            detail=f"Step {step_number} not found for subtask {subtask_id}",
        )
    return StepResponse(**updated)


def delete_step_handler(
    table_id: str,
    step_number: int,
    project_id: str,
    task_id: str,
    subtask_id: str,
    force: bool = False,
) -> dict[str, object]:
    """Delete a step.

    Deleting passed steps requires force=True and will invalidate the parent
    subtask's passes status as a safeguard against gaming the verification system.
    """
    from ...storage.steps import StepGateError, delete_step

    try:
        result = delete_step(table_id, step_number, force=force)
    except StepGateError as e:
        raise HTTPException(
            status_code=409,
            detail={
                "message": str(e),
                "step_number": step_number,
                "requires_force": True,
            },
        ) from None
    if not result.deleted:
        raise HTTPException(
            status_code=404,
            detail=f"Step {step_number} not found for subtask {subtask_id}",
        )
    return {
        "status": "deleted",
        "project_id": project_id,
        "task_id": task_id,
        "subtask_id": subtask_id,
        "step_number": step_number,
        "was_passed": result.was_passed,
        "subtask_invalidated": result.subtask_invalidated,
    }
