"""Tasks API - Agent execution task management for projects.

This module provides REST API endpoints for tasks:
- GET /projects/{project_id}/tasks - List tasks with optional status filter
- POST /projects/{project_id}/tasks - Create a new task
- GET /projects/{project_id}/tasks/{task_id} - Get task details
- PATCH /projects/{project_id}/tasks/{task_id} - Update task
- DELETE /projects/{project_id}/tasks/{task_id} - Delete task
- PATCH /projects/{project_id}/tasks/{task_id}/status - Update task status
- POST /projects/{project_id}/tasks/{task_id}/log - Append to progress log
- GET /projects/{project_id}/tasks/{task_id}/stream - SSE stream of progress log
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..logging_config import get_logger
from ..storage import tasks as task_store

logger = get_logger(__name__)

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


@router.patch("/projects/{project_id}/tasks/{task_id}/status", response_model=TaskResponse)
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


@router.post("/projects/{project_id}/tasks/{task_id}/log", response_model=dict[str, Any])
async def append_task_log(project_id: str, task_id: str, log_entry: TaskLogEntry) -> dict[str, Any]:
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


@router.get("/projects/{project_id}/tasks/{task_id}/stream")
async def stream_task_log(
    project_id: str,
    task_id: str,
    request: Request,
) -> StreamingResponse:
    """Stream task progress log updates via Server-Sent Events (SSE).

    Continuously polls the database for new progress log entries and streams
    them to the client. The stream ends when:
    - The task reaches a terminal status (completed, failed)
    - The client disconnects

    Args:
        project_id: Project ID
        task_id: Task ID
        request: FastAPI request (for disconnect detection)

    Returns:
        StreamingResponse with text/event-stream content type
    """
    # Verify task exists and belongs to project
    task = task_store.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    if task["project_id"] != project_id:
        raise HTTPException(
            status_code=404, detail=f"Task {task_id} not found in project {project_id}"
        )

    async def event_generator() -> AsyncGenerator[str, None]:
        """Generate SSE events for task progress."""
        last_log_length = 0
        terminal_statuses = {"completed", "failed"}
        poll_interval = 1.0  # Poll every second

        logger.info("sse_stream_started", task_id=task_id)

        try:
            # Send initial connection event
            yield _sse_event(
                "connected",
                {"task_id": task_id, "status": task["status"]},
            )

            while True:
                # Check for client disconnect
                if await request.is_disconnected():
                    logger.info("sse_client_disconnected", task_id=task_id)
                    break

                # Fetch current task state
                current_task = task_store.get_task(task_id)
                if not current_task:
                    yield _sse_event("error", {"message": "Task no longer exists"})
                    break

                # Check for new log entries
                current_log = current_task.get("progress_log") or ""
                if len(current_log) > last_log_length:
                    # Extract only the new portion
                    new_content = current_log[last_log_length:]
                    last_log_length = len(current_log)

                    yield _sse_event(
                        "log",
                        {"content": new_content},
                    )

                # Send status update
                yield _sse_event(
                    "status",
                    {
                        "status": current_task["status"],
                        "total_tokens_used": current_task.get("total_tokens_used", 0),
                    },
                )

                # Check for terminal status
                if current_task["status"] in terminal_statuses:
                    yield _sse_event(
                        "complete",
                        {
                            "status": current_task["status"],
                            "error_message": current_task.get("error_message"),
                        },
                    )
                    logger.info(
                        "sse_task_completed",
                        task_id=task_id,
                        status=current_task["status"],
                    )
                    break

                await asyncio.sleep(poll_interval)

        except asyncio.CancelledError:
            logger.info("sse_stream_cancelled", task_id=task_id)
        except Exception as e:
            logger.error("sse_stream_error", task_id=task_id, error=str(e))
            yield _sse_event("error", {"message": str(e)})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


def _sse_event(event_type: str, data: dict[str, Any]) -> str:
    """Format an SSE event.

    Args:
        event_type: Event type (log, status, complete, error, connected)
        data: Event data dict

    Returns:
        Formatted SSE event string
    """
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


class StartTaskRequest(BaseModel):
    """Request model for starting task execution."""

    agent_type: str  # claude or gemini
    model: str | None = None
    allow_delegation: bool = False


@router.post("/projects/{project_id}/tasks/{task_id}/start", response_model=dict[str, Any])
async def start_task(project_id: str, task_id: str, request: StartTaskRequest) -> dict[str, Any]:
    """Start task execution with an agent.

    Creates a Celery task to execute the agent on this task.

    Args:
        project_id: Project ID
        task_id: Task ID
        request: Agent configuration

    Returns:
        Dict with status, task_id, and celery_task_id
    """
    from ..tasks.agent_runner import run_agent_task

    # Verify task exists and belongs to project
    task = task_store.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    if task["project_id"] != project_id:
        raise HTTPException(
            status_code=404, detail=f"Task {task_id} not found in project {project_id}"
        )

    # Check task is in a valid state to start
    if task["status"] not in ("pending", "paused", "failed"):
        raise HTTPException(
            status_code=400,
            detail=f"Task cannot be started from status '{task['status']}'. "
            f"Must be pending, paused, or failed.",
        )

    # Validate agent type
    valid_agents = {"claude", "gemini"}
    if request.agent_type not in valid_agents:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid agent_type '{request.agent_type}'. Must be one of: {valid_agents}",
        )

    # Start the Celery task
    celery_task = run_agent_task.delay(
        task_id=task_id,
        agent_type=request.agent_type,
        model=request.model,
    )

    logger.info(
        "task_execution_started",
        task_id=task_id,
        agent_type=request.agent_type,
        celery_task_id=celery_task.id,
    )

    return {
        "status": "started",
        "task_id": task_id,
        "celery_task_id": celery_task.id,
        "agent_type": request.agent_type,
    }
