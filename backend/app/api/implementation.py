"""Implementation execution API endpoints.

Provides REST API endpoints for:
- Starting task execution
- Executing next task
- Getting execution status
- Resuming execution
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ..services.implementation_executor import ImplementationExecutor
from ..storage import tasks as task_store
from ..storage.agent_sessions import get_session

router = APIRouter()


class StartExecutionRequest(BaseModel):
    """Request model for starting execution."""

    agent_type: str = "claude"  # 'claude' or 'gemini'


class StartExecutionResponse(BaseModel):
    """Response model for starting execution."""

    session_id: str
    task_id: str
    status: str


class ExecuteNextRequest(BaseModel):
    """Request model for executing next task."""

    session_id: str
    max_iterations: int = 5


class ExecutionResultResponse(BaseModel):
    """Response model for execution result."""

    success: bool
    iterations: int
    model_used: str
    models_tried: list[str]
    reason: str | None = None
    error: str | None = None


class ExecutionStatusResponse(BaseModel):
    """Response model for execution status."""

    session_id: str
    status: str
    current_task_id: str | None
    completed_tasks: list[str]
    iteration: int
    pre_merge_sha: str | None


class ResumeResponse(BaseModel):
    """Response model for resuming execution."""

    session_id: str
    status: str


@router.post(
    "/{project_id}/tasks/{task_id}/execute/start",
    response_model=StartExecutionResponse,
)
async def start_execution(
    project_id: str,
    task_id: str,
    request: StartExecutionRequest,
) -> StartExecutionResponse:
    """Start execution of a task.

    Creates a new agent session with initialized build_state.

    Args:
        project_id: Project ID
        task_id: Task ID to execute
        request: Request with agent_type

    Returns:
        Session ID and initial status
    """
    # Verify task exists
    task = task_store.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    if task["project_id"] != project_id:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not in project {project_id}")

    executor = ImplementationExecutor(project_id)

    try:
        session_id = executor.start_execution(task_id, request.agent_type)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return StartExecutionResponse(
        session_id=session_id,
        task_id=task_id,
        status="running",
    )


@router.post(
    "/{project_id}/tasks/{task_id}/execute/next",
    response_model=ExecutionResultResponse,
)
async def execute_next(
    project_id: str,
    task_id: str,
    request: ExecuteNextRequest,
) -> ExecutionResultResponse:
    """Execute the next task in the plan.

    Runs the iteration loop until success or exhaustion.

    Args:
        project_id: Project ID
        task_id: Task ID being executed
        request: Request with session_id and max_iterations

    Returns:
        Execution result with success status
    """
    # Verify session exists
    session = get_session(request.session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session {request.session_id} not found")

    executor = ImplementationExecutor(project_id)

    try:
        result = executor.execute_next_task(
            request.session_id,
            request.max_iterations,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return ExecutionResultResponse(
        success=result.success,
        iterations=result.iterations,
        model_used=result.model_used,
        models_tried=result.models_tried,
        reason=result.reason,
        error=result.error,
    )


@router.get(
    "/{project_id}/tasks/{task_id}/execute/status",
    response_model=ExecutionStatusResponse,
)
async def get_execution_status(
    project_id: str,
    task_id: str,
    session_id: str = Query(..., description="Session ID"),
) -> ExecutionStatusResponse:
    """Get current execution status.

    Returns build_state progress.

    Args:
        project_id: Project ID
        task_id: Task ID being executed
        session_id: Session ID to query

    Returns:
        Current execution status
    """
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    build_state = session.get("build_state") or {}

    return ExecutionStatusResponse(
        session_id=session_id,
        status=build_state.get("status", "unknown"),
        current_task_id=build_state.get("current_task_id"),
        completed_tasks=build_state.get("completed_tasks", []),
        iteration=build_state.get("iteration", 0),
        pre_merge_sha=build_state.get("pre_merge_sha"),
    )


@router.post(
    "/{project_id}/tasks/{task_id}/execute/resume",
    response_model=ResumeResponse,
)
async def resume_execution(
    project_id: str,
    task_id: str,
    session_id: str = Query(..., description="Session ID to resume"),
) -> ResumeResponse:
    """Resume execution from an existing session.

    Args:
        project_id: Project ID
        task_id: Task ID being executed
        session_id: Session ID to resume

    Returns:
        Resumed session info
    """
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    executor = ImplementationExecutor(project_id)

    try:
        resumed_id = executor.resume_execution(session_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return ResumeResponse(
        session_id=resumed_id,
        status="running",
    )
