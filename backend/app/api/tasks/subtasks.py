"""Tasks API - Subtask management.

Handles:
- get_task_subtasks (project-scoped and global)
- update_task_subtask (project-scoped and global)
- delete_task_subtask
- create_subtask_endpoint
- create_subtasks_batch

Sub-routers:
- subtasks_cleanup: cleanup_prompt_endpoint
- subtasks_citations: citation logging and acknowledgment
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from ...schemas.tasks import SubtaskCreate, SubtaskResponse, SubtaskUpdate
from .helpers import get_task_or_404, verify_task_project
from .subtasks_citations import router as citations_router
from .subtasks_cleanup import router as cleanup_router
from .subtasks_helpers import (
    create_subtask_logic,
    delete_subtask_logic,
    get_subtasks_with_summary,
    update_subtask_logic,
)

router = APIRouter()

# Include sub-routers
router.include_router(citations_router)
router.include_router(cleanup_router)


# Project-scoped endpoints
@router.get(
    "/projects/{project_id}/tasks/{task_id}/subtasks",
    response_model=dict[str, Any],
)
async def get_task_subtasks(
    project_id: str,
    task_id: str,
    include_steps: bool = Query(False, description="Include steps from table for each subtask"),
) -> dict[str, Any]:
    """Get subtasks for a task."""
    verify_task_project(task_id, project_id)
    return get_subtasks_with_summary(task_id, include_steps)


@router.patch(
    "/projects/{project_id}/tasks/{task_id}/subtasks/{subtask_id}",
    response_model=SubtaskResponse,
)
async def update_task_subtask(
    project_id: str,
    task_id: str,
    subtask_id: str,
    request: SubtaskUpdate,
) -> SubtaskResponse:
    """Update a subtask's passes status."""
    verify_task_project(task_id, project_id)
    return update_subtask_logic(task_id, subtask_id, request)


@router.delete("/projects/{project_id}/tasks/{task_id}/subtasks/{subtask_id}")
async def delete_task_subtask(
    project_id: str,
    task_id: str,
    subtask_id: str,
) -> dict[str, Any]:
    """Delete a subtask and all its steps."""
    verify_task_project(task_id, project_id)
    return delete_subtask_logic(project_id, task_id, subtask_id)


@router.post(
    "/projects/{project_id}/tasks/{task_id}/subtasks",
    response_model=SubtaskResponse,
    status_code=201,
)
async def create_subtask_endpoint(
    project_id: str,
    task_id: str,
    request: SubtaskCreate,
) -> SubtaskResponse:
    """Create a single subtask for a task."""
    verify_task_project(task_id, project_id)
    try:
        return create_subtask_logic(task_id, request)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None


@router.post(
    "/projects/{project_id}/tasks/{task_id}/subtasks/batch",
    response_model=dict[str, Any],
    status_code=201,
)
async def create_subtasks_batch(
    project_id: str,
    task_id: str,
    request: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    """Create multiple subtasks for a task in batch."""
    verify_task_project(task_id, project_id)

    from ...storage.subtasks import bulk_create_subtasks

    items = request.get("items", [])
    if not items:
        return {"created": []}

    try:
        return {"created": bulk_create_subtasks(task_id, items)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None


# Global endpoints (no project_id required - task IDs are globally unique)
@router.get("/tasks/{task_id}/subtasks", response_model=dict[str, Any])
async def get_task_subtasks_global(
    task_id: str,
    include_steps: bool = Query(False, description="Include steps for each subtask"),
) -> dict[str, Any]:
    """Get subtasks for a task (global lookup, no project context)."""
    get_task_or_404(task_id)
    return get_subtasks_with_summary(task_id, include_steps)


@router.patch("/tasks/{task_id}/subtasks/{subtask_id}", response_model=SubtaskResponse)
async def update_task_subtask_global(
    task_id: str,
    subtask_id: str,
    request: SubtaskUpdate,
) -> SubtaskResponse:
    """Update a subtask's passes status (global lookup, no project context)."""
    get_task_or_404(task_id)
    return update_subtask_logic(task_id, subtask_id, request)
