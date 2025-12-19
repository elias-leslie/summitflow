"""Tasks API - Agent execution task management for projects.

This module provides REST API endpoints for tasks:
- GET /projects/{project_id}/tasks - List tasks with optional status filter
- POST /projects/{project_id}/tasks - Create a new task
- GET /projects/{project_id}/tasks/{task_id} - Get task details
- PATCH /projects/{project_id}/tasks/{task_id} - Update task
- DELETE /projects/{project_id}/tasks/{task_id} - Delete task
- PATCH /projects/{project_id}/tasks/{task_id}/status - Update task status
- POST /projects/{project_id}/tasks/{task_id}/log - Append to progress log
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ..storage import tasks as task_store

router = APIRouter()


# Pydantic models for request/response
class TaskCreate(BaseModel):
    """Request model for creating a new task."""

    title: str
    description: str | None = None
    feature_id: int | None = None  # Database ID of feature (optional)


class TaskUpdate(BaseModel):
    """Request model for updating a task."""

    title: str | None = None
    description: str | None = None
    branch_name: str | None = None
    pull_request_url: str | None = None


class TaskStatusUpdate(BaseModel):
    """Request model for updating task status."""

    status: str  # pending, running, paused, failed, completed
    error_message: str | None = None


class TaskLogEntry(BaseModel):
    """Request model for appending to progress log."""

    entry: str


class TaskResponse(BaseModel):
    """Response model for a task."""

    id: str
    project_id: str
    feature_id: int | None
    title: str
    description: str | None
    status: str
    current_criterion_id: str | None
    spec_content: str | None
    plan_content: dict | None
    progress_log: str | None
    error_message: str | None
    branch_name: str | None
    commits: list[str]
    pull_request_url: str | None
    total_sessions: int
    total_tokens_used: int
    created_at: str | None
    started_at: str | None
    completed_at: str | None


class TaskListResponse(BaseModel):
    """Response model for list of tasks."""

    tasks: list[TaskResponse]
    total: int


def _task_to_response(task: dict[str, Any]) -> TaskResponse:
    """Convert task dict to response model."""
    return TaskResponse(
        id=task["id"],
        project_id=task["project_id"],
        feature_id=task["feature_id"],
        title=task["title"],
        description=task["description"],
        status=task["status"],
        current_criterion_id=task["current_criterion_id"],
        spec_content=task["spec_content"],
        plan_content=task["plan_content"],
        progress_log=task["progress_log"],
        error_message=task["error_message"],
        branch_name=task["branch_name"],
        commits=task["commits"] or [],
        pull_request_url=task["pull_request_url"],
        total_sessions=task["total_sessions"],
        total_tokens_used=task["total_tokens_used"],
        created_at=task["created_at"].isoformat() if task["created_at"] else None,
        started_at=task["started_at"].isoformat() if task["started_at"] else None,
        completed_at=task["completed_at"].isoformat() if task["completed_at"] else None,
    )


# Endpoints
@router.get("/projects/{project_id}/tasks", response_model=TaskListResponse)
async def list_tasks(
    project_id: str,
    status: str | None = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=500, description="Results per page"),
    offset: int = Query(0, ge=0, description="Results offset"),
) -> TaskListResponse:
    """List tasks for a project.

    Query params:
        - status: Filter by status (pending, running, paused, failed, completed)
        - limit: Results per page (default 50, max 500)
        - offset: Results offset for pagination
    """
    tasks = task_store.list_tasks(project_id, status_filter=status, limit=limit, offset=offset)
    return TaskListResponse(
        tasks=[_task_to_response(t) for t in tasks],
        total=len(tasks),  # TODO: Add proper total count
    )


@router.post("/projects/{project_id}/tasks", response_model=TaskResponse)
async def create_task(project_id: str, task: TaskCreate) -> TaskResponse:
    """Create a new task.

    Args:
        project_id: Project ID
        task: Task data (title, description, optional feature_id)
    """
    created = task_store.create_task(
        project_id=project_id,
        title=task.title,
        description=task.description,
        feature_id=task.feature_id,
    )
    return _task_to_response(created)


@router.get("/projects/{project_id}/tasks/{task_id}", response_model=TaskResponse)
async def get_task(project_id: str, task_id: str) -> TaskResponse:
    """Get a single task by ID.

    Args:
        project_id: Project ID
        task_id: Task ID
    """
    task = task_store.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    if task["project_id"] != project_id:
        raise HTTPException(
            status_code=404, detail=f"Task {task_id} not found in project {project_id}"
        )
    return _task_to_response(task)


@router.patch("/projects/{project_id}/tasks/{task_id}", response_model=TaskResponse)
async def update_task(project_id: str, task_id: str, update: TaskUpdate) -> TaskResponse:
    """Update a task.

    Args:
        project_id: Project ID
        task_id: Task ID
        update: Fields to update
    """
    # Verify task exists and belongs to project
    existing = task_store.get_task(task_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    if existing["project_id"] != project_id:
        raise HTTPException(
            status_code=404, detail=f"Task {task_id} not found in project {project_id}"
        )

    # Build update dict from non-None fields
    update_fields = {}
    if update.title is not None:
        update_fields["title"] = update.title
    if update.description is not None:
        update_fields["description"] = update.description
    if update.branch_name is not None:
        update_fields["branch_name"] = update.branch_name
    if update.pull_request_url is not None:
        update_fields["pull_request_url"] = update.pull_request_url

    if not update_fields:
        return _task_to_response(existing)

    updated = task_store.update_task(task_id, **update_fields)
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to update task")
    return _task_to_response(updated)


@router.delete("/projects/{project_id}/tasks/{task_id}", response_model=dict[str, Any])
async def delete_task(project_id: str, task_id: str) -> dict[str, Any]:
    """Delete a task.

    Args:
        project_id: Project ID
        task_id: Task ID
    """
    # Verify task exists and belongs to project
    existing = task_store.get_task(task_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    if existing["project_id"] != project_id:
        raise HTTPException(
            status_code=404, detail=f"Task {task_id} not found in project {project_id}"
        )

    deleted = task_store.delete_task(task_id)
    if not deleted:
        raise HTTPException(status_code=500, detail="Failed to delete task")

    return {
        "status": "deleted",
        "project_id": project_id,
        "task_id": task_id,
    }


@router.patch(
    "/projects/{project_id}/tasks/{task_id}/status", response_model=TaskResponse
)
async def update_task_status(
    project_id: str, task_id: str, update: TaskStatusUpdate
) -> TaskResponse:
    """Update task status.

    Args:
        project_id: Project ID
        task_id: Task ID
        update: New status and optional error message
    """
    # Verify task exists and belongs to project
    existing = task_store.get_task(task_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    if existing["project_id"] != project_id:
        raise HTTPException(
            status_code=404, detail=f"Task {task_id} not found in project {project_id}"
        )

    try:
        updated = task_store.update_task_status(
            task_id, update.status, error_message=update.error_message
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    if not updated:
        raise HTTPException(status_code=500, detail="Failed to update task status")
    return _task_to_response(updated)


@router.post(
    "/projects/{project_id}/tasks/{task_id}/log", response_model=dict[str, Any]
)
async def append_task_log(
    project_id: str, task_id: str, log_entry: TaskLogEntry
) -> dict[str, Any]:
    """Append an entry to the task's progress log.

    Args:
        project_id: Project ID
        task_id: Task ID
        log_entry: Log entry text
    """
    # Verify task exists and belongs to project
    existing = task_store.get_task(task_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    if existing["project_id"] != project_id:
        raise HTTPException(
            status_code=404, detail=f"Task {task_id} not found in project {project_id}"
        )

    updated = task_store.append_progress_log(task_id, log_entry.entry)
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to append to progress log")

    return {
        "status": "appended",
        "project_id": project_id,
        "task_id": task_id,
        "entry": log_entry.entry,
    }
