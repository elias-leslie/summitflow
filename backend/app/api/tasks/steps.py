"""Tasks API - Step management within subtasks.

Handles:
- get_subtask_steps
- create_steps_batch
- append_steps_to_subtask
- update_step
- delete_step_endpoint
- get_step_summary_endpoint
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from ...schemas.steps import (
    BatchStepCreate,
    BatchStepResponse,
    StepResponse,
    StepSummary,
    StepUpdate,
)
from .core import _verify_task_project

router = APIRouter()


def _get_subtask_table_id(task_id: str, subtask_id: str) -> str:
    """Generate the subtask table ID.

    Format: {task_id}-{subtask_id} e.g., "task-abc123-1.1"
    """
    return f"{task_id}-{subtask_id}"


def _convert_steps_to_storage_format(
    steps: list[str | Any],
) -> list[str | dict[str, Any]]:
    """Convert BatchStepCreate.steps to storage format.

    Handles both strings and StepInput objects.
    """
    result: list[str | dict[str, Any]] = []
    for step in steps:
        if isinstance(step, str):
            result.append(step)
        else:
            # StepInput object - convert to dict
            result.append({"description": step.description, "spec": step.spec})
    return result


@router.get(
    "/projects/{project_id}/tasks/{task_id}/subtasks/{subtask_id}/steps",
    response_model=list[StepResponse],
)
async def get_subtask_steps(
    project_id: str,
    task_id: str,
    subtask_id: str,
) -> list[StepResponse]:
    """Get steps for a subtask.

    Args:
        project_id: Project ID
        task_id: Task ID
        subtask_id: Subtask ID (e.g., "1.1")

    Returns:
        List of steps ordered by step_number
    """
    _verify_task_project(task_id, project_id)

    from ...storage.steps import get_steps_for_subtask

    table_id = _get_subtask_table_id(task_id, subtask_id)
    steps = get_steps_for_subtask(table_id)

    return [StepResponse(**s) for s in steps]


@router.post(
    "/projects/{project_id}/tasks/{task_id}/subtasks/{subtask_id}/steps/batch",
    response_model=BatchStepResponse,
    status_code=201,
)
async def create_steps_batch(
    project_id: str,
    task_id: str,
    subtask_id: str,
    request: BatchStepCreate,
) -> BatchStepResponse:
    """Create multiple steps for a subtask in batch.

    Steps are automatically numbered starting from 1.

    Args:
        project_id: Project ID
        task_id: Task ID
        subtask_id: Subtask ID (e.g., "1.1")
        request: List of step descriptions

    Returns:
        Created steps with count
    """
    _verify_task_project(task_id, project_id)

    from ...storage.steps import bulk_create_steps

    table_id = _get_subtask_table_id(task_id, subtask_id)
    steps = _convert_steps_to_storage_format(request.steps)

    try:
        created = bulk_create_steps(table_id, steps)
    except Exception as e:
        error_msg = str(e)
        if "violates foreign key constraint" in error_msg.lower():
            raise HTTPException(
                status_code=404,
                detail=f"Subtask {subtask_id} not found for task {task_id}",
            ) from None
        raise HTTPException(status_code=500, detail=error_msg) from None

    return BatchStepResponse(
        created=[StepResponse(**s) for s in created],
        count=len(created),
    )


@router.post(
    "/projects/{project_id}/tasks/{task_id}/subtasks/{subtask_id}/steps/append",
    response_model=BatchStepResponse,
    status_code=201,
)
async def append_steps_to_subtask(
    project_id: str,
    task_id: str,
    subtask_id: str,
    request: BatchStepCreate,
) -> BatchStepResponse:
    """Append steps to a subtask, continuing from the highest existing step number.

    Unlike /steps/batch which starts at 1, this finds the max step_number
    and continues from there. Safe to call on subtasks with existing steps.

    Args:
        project_id: Project ID
        task_id: Task ID
        subtask_id: Subtask ID (e.g., "1.1")
        request: List of step descriptions to append

    Returns:
        BatchStepResponse with created steps.
    """
    _verify_task_project(task_id, project_id)

    from ...storage.steps import append_steps

    table_id = _get_subtask_table_id(task_id, subtask_id)
    steps = _convert_steps_to_storage_format(request.steps)

    try:
        created = append_steps(table_id, steps)
    except Exception as e:
        error_msg = str(e)
        if "violates foreign key constraint" in error_msg.lower():
            raise HTTPException(
                status_code=404,
                detail=f"Subtask {subtask_id} not found for task {task_id}",
            ) from None
        raise HTTPException(status_code=500, detail=error_msg) from None

    return BatchStepResponse(
        created=[StepResponse(**s) for s in created],
        count=len(created),
    )


@router.patch(
    "/projects/{project_id}/tasks/{task_id}/subtasks/{subtask_id}/steps/{step_number}",
    response_model=StepResponse,
)
async def update_step(
    project_id: str,
    task_id: str,
    subtask_id: str,
    step_number: int,
    request: StepUpdate,
) -> StepResponse:
    """Update a step's passes status.

    Args:
        project_id: Project ID
        task_id: Task ID
        subtask_id: Subtask ID (e.g., "1.1")
        step_number: Step number (1-indexed)
        request: Update with passes boolean

    Returns:
        Updated step
    """
    _verify_task_project(task_id, project_id)

    from ...storage.steps import StepGateError, update_step_passes

    table_id = _get_subtask_table_id(task_id, subtask_id)
    try:
        updated = update_step_passes(table_id, step_number, request.passes, force=request.force)
    except StepGateError as e:
        raise HTTPException(
            status_code=400,
            detail={
                "message": str(e),
                "missing_steps": e.missing_steps,
            },
        ) from e

    if updated is None:
        raise HTTPException(
            status_code=404,
            detail=f"Step {step_number} not found for subtask {subtask_id}",
        )

    return StepResponse(**updated)


@router.delete("/projects/{project_id}/tasks/{task_id}/subtasks/{subtask_id}/steps/{step_number}")
async def delete_step_endpoint(
    project_id: str,
    task_id: str,
    subtask_id: str,
    step_number: int,
) -> dict[str, Any]:
    """Delete a single step from a subtask.

    Args:
        project_id: Project ID
        task_id: Task ID
        subtask_id: Subtask ID (e.g., "1.1")
        step_number: Step number to delete (1-indexed)

    Returns:
        Deletion confirmation with details.
    """
    _verify_task_project(task_id, project_id)

    from ...storage.steps import delete_step

    table_id = _get_subtask_table_id(task_id, subtask_id)
    deleted = delete_step(table_id, step_number)
    if not deleted:
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
    }


@router.get(
    "/projects/{project_id}/tasks/{task_id}/subtasks/{subtask_id}/steps/summary",
    response_model=StepSummary,
)
async def get_step_summary_endpoint(
    project_id: str,
    task_id: str,
    subtask_id: str,
) -> StepSummary:
    """Get step completion summary for a subtask.

    Args:
        project_id: Project ID
        task_id: Task ID
        subtask_id: Subtask ID (e.g., "1.1")

    Returns:
        Summary with total, completed, progress_percent
    """
    _verify_task_project(task_id, project_id)

    from ...storage.steps import get_step_summary

    table_id = _get_subtask_table_id(task_id, subtask_id)
    summary = get_step_summary(table_id)

    return StepSummary(**summary)
