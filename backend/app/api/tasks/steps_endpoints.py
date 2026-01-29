"""Endpoint handler implementations for step operations.

This module contains the business logic for step CRUD operations,
extracted from the main steps.py router file.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from ...schemas.steps import (
    BatchStepCreate,
    BatchStepResponse,
    StepCreateWithVerification,
    StepFieldsUpdate,
    StepInsert,
    StepResponse,
    StepSummary,
)
from .steps_handlers import handle_foreign_key_error
from .steps_helpers import convert_steps_to_storage_format


def get_steps_handler(table_id: str) -> list[StepResponse]:
    """Get all steps for a subtask.

    Args:
        table_id: Subtask table ID

    Returns:
        List of steps as StepResponse objects
    """
    from ...storage.steps import get_steps_for_subtask

    steps = get_steps_for_subtask(table_id)
    return [StepResponse(**s) for s in steps]


def create_batch_handler(
    table_id: str,
    request: BatchStepCreate,
    subtask_id: str,
    task_id: str,
) -> BatchStepResponse:
    """Create multiple steps in batch.

    Args:
        table_id: Subtask table ID
        request: Batch creation request
        subtask_id: Subtask ID for error messages
        task_id: Task ID for error messages

    Returns:
        BatchStepResponse with created steps
    """
    from ...storage.steps import bulk_create_steps

    steps = convert_steps_to_storage_format(request.steps)

    try:
        created = bulk_create_steps(table_id, steps)
    except Exception as e:
        handle_foreign_key_error(e, subtask_id, task_id)

    return BatchStepResponse(
        created=[StepResponse(**s) for s in created],
        count=len(created),
    )


def append_steps_handler(
    table_id: str,
    request: BatchStepCreate,
    subtask_id: str,
    task_id: str,
) -> BatchStepResponse:
    """Append steps to a subtask.

    Args:
        table_id: Subtask table ID
        request: Batch creation request
        subtask_id: Subtask ID for error messages
        task_id: Task ID for error messages

    Returns:
        BatchStepResponse with created steps
    """
    from ...storage.steps import append_steps

    steps = convert_steps_to_storage_format(request.steps)

    try:
        created = append_steps(table_id, steps)
    except Exception as e:
        handle_foreign_key_error(e, subtask_id, task_id)

    return BatchStepResponse(
        created=[StepResponse(**s) for s in created],
        count=len(created),
    )


def insert_step_handler(
    table_id: str,
    position: int,
    request: StepInsert,
    subtask_id: str,
    task_id: str,
) -> StepResponse:
    """Insert a step at a specific position.

    Args:
        table_id: Subtask table ID
        position: Position to insert at
        request: Step insert request
        subtask_id: Subtask ID for error messages
        task_id: Task ID for error messages

    Returns:
        Created step as StepResponse
    """
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
    """Create a step with verification.

    Args:
        table_id: Subtask table ID
        request: Step creation request
        subtask_id: Subtask ID for error messages
        task_id: Task ID for error messages

    Returns:
        Created step as StepResponse
    """
    from ...storage.steps import create_step, get_steps_for_subtask

    # Find next step number
    existing_steps = get_steps_for_subtask(table_id)
    next_number = max((s["step_number"] for s in existing_steps), default=0) + 1

    try:
        created = create_step(
            subtask_id=table_id,
            step_number=next_number,
            description=request.description,
            spec=request.spec,
            verify_command=request.verify_command,
            expected_output=request.expected_output,
        )
    except Exception as e:
        handle_foreign_key_error(e, subtask_id, task_id)

    return StepResponse(**created)


def update_fields_handler(
    table_id: str,
    step_number: int,
    request: StepFieldsUpdate,
    subtask_id: str,
) -> StepResponse:
    """Update step fields.

    Args:
        table_id: Subtask table ID
        step_number: Step number to update
        request: Fields update request
        subtask_id: Subtask ID for error messages

    Returns:
        Updated step as StepResponse
    """
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
) -> dict[str, Any]:
    """Delete a step.

    Deleting passed steps requires force=True and will invalidate the parent
    subtask's passes status as a safeguard against gaming the verification system.

    Args:
        table_id: Subtask table ID
        step_number: Step number to delete
        project_id: Project ID for response
        task_id: Task ID for response
        subtask_id: Subtask ID for error messages
        force: If True, allow deletion of passed steps

    Returns:
        Deletion confirmation dict with audit info
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


def get_summary_handler(table_id: str) -> StepSummary:
    """Get step summary for a subtask.

    Args:
        table_id: Subtask table ID

    Returns:
        Step summary
    """
    from ...storage.steps import get_step_summary

    summary = get_step_summary(table_id)
    return StepSummary(**summary)
