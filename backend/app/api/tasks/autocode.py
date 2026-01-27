"""Tasks API - Autocode execution endpoint.

Handles:
- POST /projects/{project_id}/tasks/{task_id}/autocode: Dispatch task to AI worker
- GET /projects/{project_id}/tasks/{task_id}/autocode/{execution_id}: Get execution status
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ...logging_config import get_logger
from ...services.agent_hub import (
    AgentHubService,
    ExecutionState,
    TaskContext,
)
from ...storage import quality_check_results as qcr_store
from ...storage import tasks as task_store
from ...storage.connection import get_connection
from ...storage.subtasks import get_subtasks_for_task

logger = get_logger(__name__)

router = APIRouter()

# In-memory execution state storage (for MVP, migrate to DB later)
_executions: dict[str, ExecutionState] = {}
_services: dict[str, AgentHubService] = {}


class AutocodeRequest(BaseModel):
    """Request to start autocode execution."""

    model: str | None = Field(default=None, description="Model to use for execution")
    dry_run: bool = Field(default=False, description="If true, validate but don't execute")


class AutocodeResponse(BaseModel):
    """Response from autocode execution start."""

    execution_id: str = Field(description="Unique execution ID for status polling")
    task_id: str = Field(description="Task being executed")
    subtask_id: str = Field(description="Current subtask being executed")
    status: str = Field(description="Execution status: pending, running, completed, failed")
    message: str | None = Field(default=None, description="Status message")


class ExecutionStatusResponse(BaseModel):
    """Response for execution status check."""

    execution_id: str
    task_id: str
    subtask_id: str | None
    status: str
    started_at: str | None
    completed_at: str | None
    retries: int
    evidence: dict[str, Any] | None = None


def _get_first_incomplete_subtask(
    task_id: str,
) -> dict[str, Any] | None:
    """Get the first incomplete subtask for a task."""
    subtasks = get_subtasks_for_task(task_id, include_steps=True)
    for subtask in subtasks:
        if not subtask.get("passes", False):
            return subtask
    return None


def _build_task_context(
    task: dict[str, Any],
    subtask: dict[str, Any],
) -> TaskContext:
    """Build TaskContext for worker execution."""
    steps = subtask.get("steps", [])
    step_dicts = [
        {"description": s.get("description", ""), "step_number": s.get("step_number", i + 1)}
        for i, s in enumerate(steps)
    ]

    # spirit_anti is a string, but constraints expects list[str]
    spirit_anti = task.get("spirit_anti")
    constraints = [spirit_anti] if spirit_anti else None

    return TaskContext(
        task_id=task["id"],
        subtask_id=subtask["subtask_id"],
        project_id=task["project_id"],
        description=subtask.get("description", ""),
        steps=step_dicts,
        objective=task.get("objective"),
        done_when=task.get("done_when"),
        constraints=constraints,
    )


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
    # 1. Verify task exists and belongs to project
    task = task_store.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    if task["project_id"] != project_id:
        raise HTTPException(
            status_code=404, detail=f"Task {task_id} not found in project {project_id}"
        )

    # 2. Validate task has subtasks
    subtasks = get_subtasks_for_task(task_id)
    if not subtasks:
        raise HTTPException(
            status_code=400,
            detail=f"Task {task_id} has no subtasks. Cannot run autocode without subtasks.",
        )

    # 3. Validate task has done_when criteria (now included via JOIN in get_task)
    done_when = task.get("done_when")
    if not done_when:
        raise HTTPException(
            status_code=400,
            detail=f"Task {task_id} has no done_when criteria. Cannot run autocode without acceptance criteria.",
        )

    # 3.5 Check quality gate status - auto-fix and block if failing
    with get_connection() as conn:
        health = qcr_store.get_project_health_summary(conn, project_id)
        if not health["overall_pass"] and health["total_unfixed"] > 0:
            # Auto-trigger fix agent
            from app.services.quality_gate import fix_unfixed_errors
            from app.services.quality_gate.test_fix_agent import fix_failing_tests

            logger.info(
                "quality_gate_auto_fix_triggered",
                project_id=project_id,
                unfixed_count=health["total_unfixed"],
            )

            # Try to fix lint/type errors first
            lint_results = fix_unfixed_errors(conn, project_id, limit=20)
            # Then test failures
            test_results = fix_failing_tests(conn, project_id, limit=5)
            conn.commit()

            total_fixed = lint_results["fixed"] + test_results["fixed"]
            total_escalated = lint_results["escalated"] + test_results["escalated"]

            # Re-check health after fix attempt
            health = qcr_store.get_project_health_summary(conn, project_id)

            if not health["overall_pass"] and health["total_unfixed"] > 0:
                failing_checks = [
                    f"{ct}: {info['unfixed_count']} unfixed"
                    for ct, info in health["checks"].items()
                    if info.get("unfixed_count", 0) > 0
                ]
                detail = f"Quality gate failing after auto-fix (fixed {total_fixed}, escalated {total_escalated}). Remaining: {', '.join(failing_checks)}"
                raise HTTPException(status_code=400, detail=detail)

            logger.info(
                "quality_gate_auto_fix_success",
                project_id=project_id,
                fixed=total_fixed,
            )

    # 4. Find first incomplete subtask
    incomplete_subtask = _get_first_incomplete_subtask(task_id)
    if not incomplete_subtask:
        return AutocodeResponse(
            execution_id="",
            task_id=task_id,
            subtask_id="",
            status="completed",
            message="All subtasks already complete",
        )

    # 5. Generate execution ID
    execution_id = f"exec-{uuid.uuid4().hex[:12]}"

    # 6. If dry run, return without executing
    if request.dry_run:
        return AutocodeResponse(
            execution_id=execution_id,
            task_id=task_id,
            subtask_id=incomplete_subtask["subtask_id"],
            status="dry_run",
            message=f"Would execute subtask {incomplete_subtask['subtask_id']}: {incomplete_subtask.get('description', '')}",
        )

    # 7. Build task context and dispatch to Agent Hub
    task_context = _build_task_context(task, incomplete_subtask)

    try:
        # Get or create service for project
        if project_id not in _services:
            _services[project_id] = AgentHubService(project_id, model=request.model)

        service = _services[project_id]

        # Create execution state
        from datetime import UTC, datetime

        state = ExecutionState(
            execution_id=execution_id,
            task_id=task_id,
            current_subtask_id=incomplete_subtask["subtask_id"],
            status="running",
            started_at=datetime.now(UTC),
        )
        _executions[execution_id] = state

        # Note: execution_id stored in memory only for MVP
        # Future: add execution_id column to tasks table

        logger.info(
            "autocode_started",
            task_id=task_id,
            subtask_id=incomplete_subtask["subtask_id"],
            execution_id=execution_id,
        )

        # Dispatch to worker (synchronous for MVP)
        evidence = service.dispatch_task(task_context)

        # Update execution state
        state.status = "completed" if evidence.status == "completed" else "failed"
        state.evidence = evidence
        state.completed_at = datetime.now(UTC)

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

        if execution_id in _executions:
            _executions[execution_id].status = "failed"

        raise HTTPException(
            status_code=500,
            detail=f"Autocode execution failed: {e}",
        ) from e


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
    # Verify task belongs to project
    task = task_store.get_task(task_id)
    if not task or task["project_id"] != project_id:
        raise HTTPException(
            status_code=404,
            detail=f"Task {task_id} not found in project {project_id}",
        )

    state = _executions.get(execution_id)
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
    # Verify task belongs to project
    task = task_store.get_task(task_id)
    if not task or task["project_id"] != project_id:
        raise HTTPException(
            status_code=404,
            detail=f"Task {task_id} not found in project {project_id}",
        )

    state = _executions.get(execution_id)
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
            detail=f"Cannot abort execution in status '{state.status}'. Only running executions can be aborted.",
        )

    # Mark as aborted
    from datetime import UTC, datetime

    state.status = "aborted"
    state.completed_at = datetime.now(UTC)

    # Close the service if exists
    if project_id in _services:
        _services[project_id].close()
        del _services[project_id]

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


# =============================================================================
# Manual Execution Endpoint (Orchestrator-based)
# =============================================================================


class ExecuteRequest(BaseModel):
    """Request to start orchestrator execution."""

    worker_id: str | None = Field(default=None, description="Optional worker ID for claiming")
    lock_duration_minutes: int = Field(default=60, description="Lock duration in minutes")


class ExecuteResponse(BaseModel):
    """Response from execute API."""

    execution_id: str = Field(description="Celery task ID for tracking")
    task_id: str = Field(description="Task being executed")
    status: str = Field(description="queued, running, completed, failed")
    message: str | None = Field(default=None, description="Status message")


# Valid statuses for execution
EXECUTABLE_STATUSES = {"pending", "planning", "paused", "failed"}


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
    from ...tasks.orchestrator_runner import execute_orchestrator_task

    # 1. Verify task exists and belongs to project
    task = task_store.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    if task["project_id"] != project_id:
        raise HTTPException(
            status_code=404, detail=f"Task {task_id} not found in project {project_id}"
        )

    # 2. Validate task status
    status = task.get("status", "pending")
    if status not in EXECUTABLE_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Task {task_id} is in status '{status}'. Only tasks in {EXECUTABLE_STATUSES} can be executed.",
        )

    # 3. Validate task has subtasks
    subtasks = get_subtasks_for_task(task_id)
    if not subtasks:
        raise HTTPException(
            status_code=400,
            detail=f"Task {task_id} has no subtasks. Run /plan_it first.",
        )

    # 4. Parse request or use defaults
    worker_id = request.worker_id if request else None
    lock_duration = request.lock_duration_minutes if request else 60

    # 5. Queue execution via Celery
    execution_id = f"exec-{uuid.uuid4().hex[:12]}"

    logger.info(
        "task_execution_queued",
        task_id=task_id,
        execution_id=execution_id,
        project_id=project_id,
    )

    # Queue async task
    celery_task = execute_orchestrator_task.delay(
        project_id=project_id,
        task_id=task_id,
        worker_id=worker_id,
        lock_duration_minutes=lock_duration,
    )

    # Store mapping of our execution_id to Celery task_id
    # (In memory for MVP - migrate to DB later)
    _executions[execution_id] = ExecutionState(
        execution_id=execution_id,
        task_id=task_id,
        current_subtask_id="",
        status="queued",
    )

    return ExecuteResponse(
        execution_id=celery_task.id,  # Use Celery task ID for tracking
        task_id=task_id,
        status="queued",
        message=f"Task queued for execution. Track via WebSocket /ws/execution/{task_id}",
    )
