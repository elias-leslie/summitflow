"""Tasks API - Autocode execution endpoint.

Handles:
- POST /projects/{project_id}/tasks/{task_id}/autocode: Dispatch task to AI worker
- GET /projects/{project_id}/tasks/{task_id}/autocode/{execution_id}: Get execution status
- POST /projects/{project_id}/tasks/{task_id}/autocode/{execution_id}/abort: Abort execution
- POST /projects/{project_id}/tasks/{task_id}/execute: Start orchestrator execution
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from .autocode_handlers import (
    handle_abort_execution,
    handle_execute_task,
    handle_get_execution_status,
    handle_start_autocode,
)
from .autocode_models import (
    AutocodeRequest,
    AutocodeResponse,
    ExecuteRequest,
    ExecuteResponse,
    ExecutionStatusResponse,
)

router = APIRouter()


@router.post("/projects/{project_id}/tasks/{task_id}/autocode")
def start_autocode(
    project_id: str,
    task_id: str,
    request: AutocodeRequest,
) -> AutocodeResponse:
    """Start autocode execution for a task.

    Validates task has subtasks and done_when, then dispatches
    the first incomplete subtask to Agent Hub for AI execution.

    Args:
        project_id: Project ID
        task_id: Task ID to execute
        request: Autocode configuration

    Returns:
        AutocodeResponse with execution_id for status polling

    Raises:
        HTTPException(404): Task not found or not in project
        HTTPException(400): Task not ready for autocode (no subtasks, no done_when)
    """
    return handle_start_autocode(project_id, task_id, request)


@router.get("/projects/{project_id}/tasks/{task_id}/autocode/{execution_id}")
def get_execution_status(
    project_id: str,
    task_id: str,
    execution_id: str,
) -> ExecutionStatusResponse:
    """Get status of an autocode execution.

    Args:
        project_id: Project ID
        task_id: Task ID
        execution_id: Execution ID from start_autocode

    Returns:
        ExecutionStatusResponse with current status and evidence if complete

    Raises:
        HTTPException(404): Execution not found or task not in project
    """
    return handle_get_execution_status(project_id, task_id, execution_id)


@router.post("/projects/{project_id}/tasks/{task_id}/autocode/{execution_id}/abort")
def abort_execution(
    project_id: str,
    task_id: str,
    execution_id: str,
) -> dict[str, Any]:
    """Abort a running autocode execution.

    Args:
        project_id: Project ID
        task_id: Task ID
        execution_id: Execution ID to abort

    Returns:
        Status dict with abort confirmation

    Raises:
        HTTPException(404): Execution not found or task not in project
        HTTPException(400): Execution not running (already completed/failed)
    """
    return handle_abort_execution(project_id, task_id, execution_id)


@router.post("/projects/{project_id}/tasks/{task_id}/execute")
def execute_task(
    project_id: str,
    task_id: str,
    request: ExecuteRequest | None = None,
) -> ExecuteResponse:
    """Start autonomous orchestrator execution for a task.

    Queues the task for execution via Celery with the Sonnet coordinator pattern.
    Unlike /autocode which runs synchronously on a single subtask, this executes
    all subtasks asynchronously with WebSocket streaming.

    Args:
        project_id: Project ID
        task_id: Task ID to execute
        request: Optional execution configuration

    Returns:
        ExecuteResponse with execution_id for tracking

    Raises:
        HTTPException(404): Task not found or not in project
        HTTPException(400): Task not in executable status or has no subtasks
    """
    return handle_execute_task(project_id, task_id, request)
