"""Tasks API - Logging, streaming, and task lifecycle.

Handles:
- validate_task_ready_endpoint
- append_task_log
- stream_task_log (SSE)
- start_task
- claim_task
- release_task
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from ...constants import VALID_AGENT_TYPES
from ...logging_config import get_logger
from ...schemas.tasks import (
    ClaimTaskRequest,
    StartTaskRequest,
    TaskLogEntry,
    TaskResponse,
    ValidationResultResponse,
)
from ...services.task_validation import validate_task_ready
from ...storage import tasks as task_store
from ...utils.sse import format_sse_event as _sse_event
from .core import _get_task_or_404, _task_to_response, _verify_task_project

logger = get_logger(__name__)

router = APIRouter()


@router.post(
    "/projects/{project_id}/tasks/{task_id}/validate-ready",
    response_model=ValidationResultResponse,
)
async def validate_task_ready_endpoint(project_id: str, task_id: str) -> ValidationResultResponse:
    """Validate if a task is ready to be worked on.

    Performs pre-work validation checks:
    - Task is not already running or completed
    - Task has no incomplete blocking dependencies
    - For feature-type tasks: linked to feature with acceptance criteria
    - Criteria quality warnings (specificity, action verbs)

    Args:
        project_id: Project ID
        task_id: Task ID

    Returns:
        ValidationResultResponse with ready status, issues, and suggestions.
    """
    result = validate_task_ready(task_id, project_id)
    return ValidationResultResponse(
        ready=result.ready,
        issues=result.issues,
        suggestions=result.suggestions,
    )


@router.post("/projects/{project_id}/tasks/{task_id}/log", response_model=dict[str, Any])
async def append_task_log(project_id: str, task_id: str, log_entry: TaskLogEntry) -> dict[str, Any]:
    """Append an entry to the task's progress log.

    Args:
        project_id: Project ID
        task_id: Task ID
        log_entry: Log entry text
    """
    _verify_task_project(task_id, project_id)

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
    task = _verify_task_project(task_id, project_id)

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
    from ...tasks.agent_runner import run_agent_task

    task = _verify_task_project(task_id, project_id)

    # Check task is in a valid state to start
    if task["status"] not in ("pending", "paused", "failed"):
        raise HTTPException(
            status_code=400,
            detail=f"Task cannot be started from status '{task['status']}'. "
            f"Must be pending, paused, or failed.",
        )

    # Validate agent type
    if request.agent_type not in VALID_AGENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid agent_type '{request.agent_type}'. Must be one of: {VALID_AGENT_TYPES}",
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


@router.post("/projects/{project_id}/tasks/{task_id}/claim", response_model=TaskResponse)
async def claim_task(project_id: str, task_id: str, request: ClaimTaskRequest) -> TaskResponse:
    """Claim a task for exclusive execution.

    Uses database locking to prevent race conditions when multiple workers
    try to claim the same task.

    Args:
        project_id: Project ID
        task_id: Task ID to claim
        request: Claim details (worker_id, lock_minutes)

    Returns:
        The claimed task.

    Raises:
        HTTPException(404): Task not found
        HTTPException(409): Task already claimed or not in claimable status
    """
    _verify_task_project(task_id, project_id)

    claimed = task_store.claim_task(
        task_id=task_id,
        worker_id=request.worker_id,
        lock_duration_minutes=request.lock_minutes,
    )

    if not claimed:
        raise HTTPException(
            status_code=409,
            detail=f"Task {task_id} is not available for claiming. "
            "It may already be claimed or not in a claimable status (pending/paused/failed).",
        )

    return _task_to_response(claimed)


@router.post("/projects/{project_id}/tasks/{task_id}/release", response_model=TaskResponse)
async def release_task(project_id: str, task_id: str) -> TaskResponse:
    """Release a claimed task back to pending status.

    Clears the claim and resets status to pending, allowing other workers
    to claim and work on it.

    Args:
        project_id: Project ID
        task_id: Task ID to release

    Returns:
        The released task.

    Raises:
        HTTPException(404): Task not found
        HTTPException(400): Task not currently claimed
    """
    task = _verify_task_project(task_id, project_id)

    if not task.get("claimed_by"):
        raise HTTPException(
            status_code=400,
            detail=f"Task {task_id} is not currently claimed.",
        )

    released = task_store.release_task(task_id)

    if not released:
        raise HTTPException(status_code=500, detail="Failed to release task")

    return _task_to_response(released)


# Global endpoints (no project_id required - task IDs are globally unique)


@router.post("/tasks/{task_id}/log", response_model=dict[str, Any])
async def append_task_log_global(task_id: str, log_entry: TaskLogEntry) -> dict[str, Any]:
    """Append an entry to the task's progress log (global lookup, no project context required).

    Args:
        task_id: Task ID
        log_entry: Log entry text
    """
    task = _get_task_or_404(task_id)

    updated = task_store.append_progress_log(task_id, log_entry.entry)
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to append to progress log")

    return {
        "status": "appended",
        "project_id": task["project_id"],
        "task_id": task_id,
        "entry": log_entry.entry,
    }
