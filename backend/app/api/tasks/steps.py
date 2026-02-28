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

from fastapi import APIRouter

from ...schemas.steps import (
    BatchStepCreate,
    BatchStepResponse,
    StepCreateWithVerification,
    StepFieldsUpdate,
    StepInsert,
    StepResponse,
    StepSummary,
    StepUpdate,
)
from .helpers import get_task_or_404, verify_task_project
from .steps_endpoints import (
    append_steps_handler,
    create_batch_handler,
    create_with_verification_handler,
    delete_step_handler,
    get_steps_handler,
    get_summary_handler,
    insert_step_handler,
    update_fields_handler,
)
from .steps_handlers import handle_update_step_passes, handle_update_step_status
from .subtasks_helpers import get_subtask_table_id, get_verification_cwd

router = APIRouter()


@router.get(
    "/projects/{project_id}/tasks/{task_id}/subtasks/{subtask_id}/steps",
    response_model=list[StepResponse],
)
async def get_subtask_steps(
    project_id: str,
    task_id: str,
    subtask_id: str,
) -> list[StepResponse]:
    """Get steps for a subtask."""
    verify_task_project(task_id, project_id)
    table_id = get_subtask_table_id(task_id, subtask_id)
    return get_steps_handler(table_id)


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
    """Create multiple steps for a subtask in batch."""
    verify_task_project(task_id, project_id)
    table_id = get_subtask_table_id(task_id, subtask_id)
    return create_batch_handler(table_id, request, subtask_id, task_id)


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
    """Append steps to a subtask, continuing from the highest existing step number."""
    verify_task_project(task_id, project_id)
    table_id = get_subtask_table_id(task_id, subtask_id)
    return append_steps_handler(table_id, request, subtask_id, task_id)


@router.post(
    "/projects/{project_id}/tasks/{task_id}/subtasks/{subtask_id}/steps/{position}/insert",
    response_model=StepResponse,
    status_code=201,
)
async def insert_step_at_position(
    project_id: str,
    task_id: str,
    subtask_id: str,
    position: int,
    request: StepInsert,
) -> StepResponse:
    """Insert a step at a specific position, shifting existing steps down."""
    verify_task_project(task_id, project_id)
    table_id = get_subtask_table_id(task_id, subtask_id)
    return insert_step_handler(table_id, position, request, subtask_id, task_id)


@router.post(
    "/projects/{project_id}/tasks/{task_id}/subtasks/{subtask_id}/steps",
    response_model=StepResponse,
    status_code=201,
)
async def create_step_with_verification(
    project_id: str,
    task_id: str,
    subtask_id: str,
    request: StepCreateWithVerification,
) -> StepResponse:
    """Create a single step with required verification."""
    verify_task_project(task_id, project_id)
    table_id = get_subtask_table_id(task_id, subtask_id)
    return create_with_verification_handler(table_id, request, subtask_id, task_id)


@router.patch(
    "/projects/{project_id}/tasks/{task_id}/subtasks/{subtask_id}/steps/{step_number}/fields",
    response_model=StepResponse,
)
async def update_step_fields(
    project_id: str,
    task_id: str,
    subtask_id: str,
    step_number: int,
    request: StepFieldsUpdate,
) -> StepResponse:
    """Update step description."""
    verify_task_project(task_id, project_id)
    table_id = get_subtask_table_id(task_id, subtask_id)
    return update_fields_handler(table_id, step_number, request, subtask_id)


@router.patch(
    "/projects/{project_id}/tasks/{task_id}/subtasks/{subtask_id}/steps/{step_number}/status",
    response_model=StepResponse,
)
async def update_step_status(
    project_id: str,
    task_id: str,
    subtask_id: str,
    step_number: int,
    request: dict[str, Any],
) -> StepResponse:
    """Update step status (pending, passed, failed, plan_defect)."""
    verify_task_project(task_id, project_id)
    table_id = get_subtask_table_id(task_id, subtask_id)
    return handle_update_step_status(table_id, step_number, request)


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
    """Update a step's passes status."""
    verify_task_project(task_id, project_id)
    table_id = get_subtask_table_id(task_id, subtask_id)
    verification_cwd = get_verification_cwd(project_id, task_id)
    return handle_update_step_passes(
        table_id, step_number, request.passes, verification_cwd,
        project_id=project_id,
    )


@router.delete("/projects/{project_id}/tasks/{task_id}/subtasks/{subtask_id}/steps/{step_number}")
async def delete_step_endpoint(
    project_id: str,
    task_id: str,
    subtask_id: str,
    step_number: int,
    force: bool = False,
) -> dict[str, Any]:
    """Delete a single step from a subtask.

    Deleting passed steps requires force=True and will invalidate the parent
    subtask's passes status. This is a safeguard against gaming the verification
    system by deleting steps that have already been verified.
    """
    verify_task_project(task_id, project_id)
    table_id = get_subtask_table_id(task_id, subtask_id)
    return delete_step_handler(table_id, step_number, project_id, task_id, subtask_id, force=force)


@router.get(
    "/projects/{project_id}/tasks/{task_id}/subtasks/{subtask_id}/steps/summary",
    response_model=StepSummary,
)
async def get_step_summary_endpoint(
    project_id: str,
    task_id: str,
    subtask_id: str,
) -> StepSummary:
    """Get step completion summary for a subtask."""
    verify_task_project(task_id, project_id)
    table_id = get_subtask_table_id(task_id, subtask_id)
    return get_summary_handler(table_id)


# Global endpoints (no project_id required - task IDs are globally unique)


@router.patch(
    "/tasks/{task_id}/subtasks/{subtask_id}/steps/{step_number}/status",
    response_model=StepResponse,
)
async def update_step_status_global(
    task_id: str,
    subtask_id: str,
    step_number: int,
    request: dict[str, Any],
) -> StepResponse:
    """Update step status (global, no project context required)."""
    get_task_or_404(task_id)
    table_id = get_subtask_table_id(task_id, subtask_id)
    return handle_update_step_status(table_id, step_number, request)


@router.patch(
    "/tasks/{task_id}/subtasks/{subtask_id}/steps/{step_number}",
    response_model=StepResponse,
)
async def update_step_global(
    task_id: str,
    subtask_id: str,
    step_number: int,
    request: StepUpdate,
) -> StepResponse:
    """Update a step's passes status (global, no project context required)."""
    task = get_task_or_404(task_id)
    table_id = get_subtask_table_id(task_id, subtask_id)
    project_id = task.get("project_id")
    verification_cwd = get_verification_cwd(project_id, task_id) if project_id else None
    return handle_update_step_passes(
        table_id, step_number, request.passes, verification_cwd,
        project_id=project_id,
    )
