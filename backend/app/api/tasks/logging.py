"""Tasks API - Logging and task lifecycle.

Handles:
- validate_task_ready_endpoint
- append_task_log
- start_task
- claim_task
- release_task
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from ...logging_config import get_logger
from ...schemas.tasks import (
    ClaimTaskRequest,
    StartTaskRequest,
    TaskLogEntry,
    TaskResponse,
    ValidationResultResponse,
)
from ...services.task_validation import validate_task_ready
from ...storage import log_task_event
from ...storage import tasks as task_store
from .autocode_handlers import _validate_agent_slug
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

    updated = log_task_event(task_id, log_entry.entry)
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to append to progress log")

    return {
        "status": "appended",
        "project_id": project_id,
        "task_id": task_id,
        "entry": log_entry.entry,
    }


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

    # Validate agent_slug is provided
    agent_slug = _validate_agent_slug(request.agent_slug)

    task = _verify_task_project(task_id, project_id)

    # Check task is in a valid state to start
    if task["status"] not in ("pending", "paused", "failed"):
        raise HTTPException(
            status_code=400,
            detail=f"Task cannot be started from status '{task['status']}'. "
            f"Must be pending, paused, or failed.",
        )

    # Start the Celery task
    celery_task = run_agent_task.delay(
        task_id=task_id,
        agent_slug=agent_slug,
    )

    logger.info(
        "task_execution_started",
        task_id=task_id,
        agent_slug=agent_slug,
        celery_task_id=celery_task.id,
    )

    return {
        "status": "started",
        "task_id": task_id,
        "celery_task_id": celery_task.id,
        "agent_slug": agent_slug,
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

    updated = log_task_event(task_id, log_entry.entry)
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to append to progress log")

    return {
        "status": "appended",
        "project_id": task["project_id"],
        "task_id": task_id,
        "entry": log_entry.entry,
    }
