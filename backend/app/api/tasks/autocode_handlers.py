"""Autocode endpoint handlers.

Business logic for autocode API endpoints.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException

from ...logging_config import get_logger
from ...services.agent_hub import ExecutionState
from ...storage import tasks as task_store
from ...storage.subtasks import get_subtasks_for_task
from .autocode_execution import (
    _executions,
    build_task_context,
    close_service,
    create_execution_state,
    generate_execution_id,
    get_execution_state,
    get_first_incomplete_subtask,
    get_or_create_service,
    update_execution_completed,
    update_execution_failed,
)
from .autocode_models import (
    EXECUTABLE_STATUSES,
    AutocodeRequest,
    AutocodeResponse,
    ExecuteRequest,
    ExecuteResponse,
    ExecutionStatusResponse,
)
from .autocode_validation import (
    check_and_fix_quality_gates,
    validate_has_done_when,
    validate_has_subtasks,
    validate_task_exists,
    validate_task_in_project,
)

logger = get_logger(__name__)


def handle_start_autocode(
    project_id: str,
    task_id: str,
    request: AutocodeRequest,
) -> AutocodeResponse:
    """Handle autocode execution start request.

    Args:
        project_id: Project ID
        task_id: Task ID
        request: Autocode request

    Returns:
        AutocodeResponse
    """
    # Verify task exists and belongs to project
    task = task_store.get_task(task_id)
    validate_task_exists(task, task_id)
    assert task is not None
    validate_task_in_project(task, task_id, project_id)

    # Validate task readiness
    validate_has_subtasks(task_id)
    validate_has_done_when(task, task_id)

    # Check quality gates and auto-fix if needed
    check_and_fix_quality_gates(project_id)

    # Find first incomplete subtask
    incomplete_subtask = get_first_incomplete_subtask(task_id)
    if not incomplete_subtask:
        return AutocodeResponse(
            execution_id="",
            task_id=task_id,
            subtask_id="",
            status="completed",
            message="All subtasks already complete",
        )

    # Generate execution ID
    execution_id = generate_execution_id()

    # Handle dry run
    if request.dry_run:
        return AutocodeResponse(
            execution_id=execution_id,
            task_id=task_id,
            subtask_id=incomplete_subtask["subtask_id"],
            status="dry_run",
            message=(
                f"Would execute subtask {incomplete_subtask['subtask_id']}: "
                f"{incomplete_subtask.get('description', '')}"
            ),
        )

    # Build task context and dispatch to Agent Hub
    task_context = build_task_context(task, incomplete_subtask)

    try:
        service = get_or_create_service(project_id, model=request.model)
        state = create_execution_state(
            execution_id,
            task_id,
            incomplete_subtask["subtask_id"],
        )

        logger.info(
            "autocode_started",
            task_id=task_id,
            subtask_id=incomplete_subtask["subtask_id"],
            execution_id=execution_id,
        )

        evidence = service.dispatch_task(task_context)
        update_execution_completed(state, evidence)

        logger.info(
            "autocode_completed",
            task_id=task_id,
            execution_id=execution_id,
            status=evidence.status,
        )

        return AutocodeResponse(
            execution_id=execution_id,
            task_id=task_id,
            subtask_id=incomplete_subtask["subtask_id"],
            status=state.status,
            message=f"Completed with status: {evidence.status}",
        )

    except Exception as e:
        logger.error(
            "autocode_error",
            task_id=task_id,
            execution_id=execution_id,
            error=str(e),
        )
        update_execution_failed(execution_id)
        raise HTTPException(
            status_code=500,
            detail=f"Autocode execution failed: {e}",
        ) from e


def handle_get_execution_status(
    project_id: str,
    task_id: str,
    execution_id: str,
) -> ExecutionStatusResponse:
    """Handle execution status request.

    Args:
        project_id: Project ID
        task_id: Task ID
        execution_id: Execution ID

    Returns:
        ExecutionStatusResponse
    """
    task = task_store.get_task(task_id)
    if not task or task["project_id"] != project_id:
        raise HTTPException(
            status_code=404,
            detail=f"Task {task_id} not found in project {project_id}",
        )

    state = get_execution_state(execution_id)
    if not state:
        raise HTTPException(
            status_code=404,
            detail=f"Execution {execution_id} not found",
        )

    if state.task_id != task_id:
        raise HTTPException(
            status_code=404,
            detail=f"Execution {execution_id} not found for task {task_id}",
        )

    evidence_dict = None
    if state.evidence:
        evidence_dict = state.evidence.to_dict()

    return ExecutionStatusResponse(
        execution_id=state.execution_id,
        task_id=state.task_id,
        subtask_id=state.current_subtask_id,
        status=state.status,
        started_at=state.started_at.isoformat() if state.started_at else None,
        completed_at=state.completed_at.isoformat() if state.completed_at else None,
        retries=state.retries,
        evidence=evidence_dict,
    )


def handle_abort_execution(
    project_id: str,
    task_id: str,
    execution_id: str,
) -> dict[str, Any]:
    """Handle execution abort request.

    Args:
        project_id: Project ID
        task_id: Task ID
        execution_id: Execution ID

    Returns:
        Status dict
    """
    task = task_store.get_task(task_id)
    if not task or task["project_id"] != project_id:
        raise HTTPException(
            status_code=404,
            detail=f"Task {task_id} not found in project {project_id}",
        )

    state = get_execution_state(execution_id)
    if not state:
        raise HTTPException(
            status_code=404,
            detail=f"Execution {execution_id} not found",
        )

    if state.task_id != task_id:
        raise HTTPException(
            status_code=404,
            detail=f"Execution {execution_id} not found for task {task_id}",
        )

    if state.status != "running":
        raise HTTPException(
            status_code=400,
            detail=(
                f"Cannot abort execution in status '{state.status}'. "
                "Only running executions can be aborted."
            ),
        )

    state.status = "aborted"
    state.completed_at = datetime.now(UTC)
    close_service(project_id)

    logger.info(
        "autocode_aborted",
        task_id=task_id,
        execution_id=execution_id,
    )

    return {
        "execution_id": execution_id,
        "task_id": task_id,
        "status": "aborted",
        "message": "Execution aborted successfully",
    }


def handle_execute_task(
    project_id: str,
    task_id: str,
    request: ExecuteRequest | None = None,
) -> ExecuteResponse:
    """Handle orchestrator execution request.

    Args:
        project_id: Project ID
        task_id: Task ID
        request: Execute request

    Returns:
        ExecuteResponse
    """
    from ...tasks.orchestrator_runner import execute_orchestrator_task

    task = task_store.get_task(task_id)
    validate_task_exists(task, task_id)
    assert task is not None
    validate_task_in_project(task, task_id, project_id)

    status = task.get("status", "pending")
    if status not in EXECUTABLE_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Task {task_id} is in status '{status}'. "
                f"Only tasks in {EXECUTABLE_STATUSES} can be executed."
            ),
        )

    subtasks = get_subtasks_for_task(task_id)
    if not subtasks:
        raise HTTPException(
            status_code=400,
            detail=f"Task {task_id} has no subtasks. Run /plan_it first.",
        )

    worker_id = request.worker_id if request else None
    lock_duration = request.lock_duration_minutes if request else 60
    execution_id = f"exec-{uuid.uuid4().hex[:12]}"

    logger.info(
        "task_execution_queued",
        task_id=task_id,
        execution_id=execution_id,
        project_id=project_id,
    )

    celery_task = execute_orchestrator_task.delay(
        project_id=project_id,
        task_id=task_id,
        worker_id=worker_id,
        lock_duration_minutes=lock_duration,
    )

    _executions[execution_id] = ExecutionState(
        execution_id=execution_id,
        task_id=task_id,
        current_subtask_id="",
        status="queued",
    )

    return ExecuteResponse(
        execution_id=celery_task.id,
        task_id=task_id,
        status="queued",
        message=f"Task queued for execution. Track via WebSocket /ws/execution/{task_id}",
    )
