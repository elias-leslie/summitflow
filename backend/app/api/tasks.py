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
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from ..constants import VALID_AGENT_TYPES
from ..logging_config import get_logger
from ..schemas.tasks import (
    AcceptanceCriterion,
    BlockerInfo,
    CapabilityContext,
    ClaimTaskRequest,
    CriteriaValidateRequest,
    CriteriaValidateResponse,
    CriterionFailure,
    CriterionLinkTestRequest,
    CriterionVerifyRequest,
    DependencyCreate,
    DependencyResponse,
    StartTaskRequest,
    TaskCreate,
    TaskListResponse,
    TaskLogEntry,
    TaskResponse,
    TaskStatusUpdate,
    TaskUpdate,
    ValidationResultResponse,
)
from ..services.criteria_validator import validate_criteria
from ..services.task_validation import validate_task_ready
from ..storage import task_dependencies as dep_store
from ..storage import tasks as task_store
from ..utils.sse import format_sse_event as _sse_event

logger = get_logger(__name__)

router = APIRouter()


def _verify_task_project(task_id: str, project_id: str) -> dict[str, Any]:
    """Get task and verify it belongs to the project.

    Args:
        task_id: Task ID to fetch
        project_id: Expected project ID

    Returns:
        Task dict if valid

    Raises:
        HTTPException(404): If task not found or belongs to different project
    """
    task = task_store.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    if task["project_id"] != project_id:
        raise HTTPException(
            status_code=404, detail=f"Task {task_id} not found in project {project_id}"
        )
    return task


def _task_to_response(task: dict[str, Any]) -> TaskResponse:
    """Convert task dict to response model."""
    # Handle optional capability context
    capability_context = None
    if task.get("capability") is not None:
        c = task["capability"]
        # Parse acceptance criteria if present
        criteria_list = None
        if c.get("acceptance_criteria"):
            criteria_list = [
                AcceptanceCriterion(
                    id=crit.get("id", "ac-000"),
                    criterion=crit.get("criterion", crit.get("description", "")),
                    category=crit.get("category", "correctness"),
                    measurement=crit.get("measurement", "test"),
                    threshold=crit.get("threshold"),
                    verified=crit.get("verified", crit.get("passes", False)),
                    verified_at=crit.get("verified_at"),
                    verified_by=crit.get("verified_by"),
                )
                for crit in c["acceptance_criteria"]
            ]
        capability_context = CapabilityContext(
            id=c["id"],
            capability_id=c["capability_id"],
            name=c["name"],
            criteria_passed=c["criteria_passed"],
            criteria_total=c["criteria_total"],
            acceptance_criteria=criteria_list,
        )

    # Handle optional blockers context
    blockers_list = None
    blocked_by_incomplete = None
    if task.get("blockers") is not None:
        blockers_list = [
            BlockerInfo(
                id=b["id"],
                title=b["title"],
                status=b["status"],
                priority=b["priority"],
            )
            for b in task["blockers"]
        ]
        blocked_by_incomplete = len(blockers_list) > 0

    # Handle task-level acceptance criteria (JSONB from storage)
    task_criteria_list = None
    if task.get("acceptance_criteria"):
        raw_criteria = task["acceptance_criteria"]
        # Storage returns list of dicts from JSONB
        if isinstance(raw_criteria, list):
            task_criteria_list = [
                AcceptanceCriterion(
                    id=crit.get("id", "ac-000"),
                    criterion=crit.get("criterion", crit.get("description", "")),
                    category=crit.get("category", "correctness"),
                    measurement=crit.get("measurement", "test"),
                    threshold=crit.get("threshold"),
                    verified=crit.get("verified", False),
                    verified_at=crit.get("verified_at"),
                    verified_by=crit.get("verified_by"),
                )
                for crit in raw_criteria
                if crit.get("id") or crit.get("criterion") or crit.get("description")
            ]

    return TaskResponse(
        id=task["id"],
        project_id=task["project_id"],
        capability_id=task["capability_id"],
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
        # Issue tracking fields
        priority=task.get("priority", 2),
        labels=task.get("labels") or [],
        task_type=task.get("task_type", "task"),
        parent_task_id=task.get("parent_task_id"),
        # AI agent reliability fields
        objective=task.get("objective"),
        acceptance_criteria=task_criteria_list,
        current_phase=task.get("current_phase"),
        verification_result=task.get("verification_result"),
        # Optional feature context
        capability=capability_context,
        # Optional blockers context
        blockers=blockers_list,
        blocked_by_incomplete=blocked_by_incomplete,
    )


# Endpoints
@router.get("/projects/{project_id}/tasks", response_model=TaskListResponse)
async def list_tasks(
    project_id: str,
    status: str | None = Query(None, description="Filter by status"),
    task_type: str | None = Query(
        None, alias="type", description="Filter by type (feature, bug, task)"
    ),
    priority: int | None = Query(None, ge=0, le=4, description="Filter by priority (0-4)"),
    labels: str | None = Query(None, description="Filter by labels (comma-separated)"),
    orphans_only: bool = Query(
        False, description="Only return tasks not linked to a feature (issues)"
    ),
    include: str | None = Query(
        None, description="Include related data (e.g., 'feature,blockers')"
    ),
    limit: int = Query(50, ge=1, le=500, description="Results per page"),
    offset: int = Query(0, ge=0, description="Results offset"),
) -> TaskListResponse:
    """List tasks for a project.

    Query params:
        - status: Filter by status (pending, running, paused, failed, completed)
        - type: Filter by task type (feature, bug, task)
        - priority: Filter by priority (0-4)
        - labels: Filter by labels (comma-separated, e.g., "complexity:small,domains:backend")
        - orphans_only: Only return tasks not linked to a capability
        - include: Include related data (comma-separated: 'capability' for capability context, 'blockers' for blocking tasks)
        - limit: Results per page (default 50, max 500)
        - offset: Results offset for pagination
    """
    labels_list = labels.split(",") if labels else None
    includes = include.split(",") if include else []
    include_blockers = "blockers" in includes

    tasks = task_store.list_tasks(
        project_id,
        status_filter=status,
        task_type_filter=task_type,
        priority_filter=priority,
        labels_filter=labels_list,
        orphans_only=orphans_only,
        limit=limit,
        offset=offset,
    )

    # Add blockers info if requested
    if include_blockers:
        for task in tasks:
            blockers = dep_store.get_blocking_tasks(task["id"])
            task["blockers"] = blockers

    return TaskListResponse(
        tasks=[_task_to_response(t) for t in tasks],
        total=len(tasks),  # TODO: Add proper total count
    )


@router.get("/projects/{project_id}/tasks/ready", response_model=TaskListResponse)
async def list_ready_tasks(
    project_id: str,
    limit: int = Query(50, ge=1, le=500, description="Results per page"),
) -> TaskListResponse:
    """List tasks that are ready to work on (not blocked by dependencies).

    Returns pending tasks with no incomplete blocking dependencies,
    ordered by priority then creation date.
    """
    tasks = task_store.list_ready_tasks(project_id, limit=limit)
    return TaskListResponse(
        tasks=[_task_to_response(t) for t in tasks],
        total=len(tasks),
    )


@router.get("/projects/{project_id}/tasks/blocked", response_model=TaskListResponse)
async def list_blocked_tasks(
    project_id: str,
    limit: int = Query(50, ge=1, le=500, description="Results per page"),
) -> TaskListResponse:
    """List tasks that are blocked by incomplete dependencies.

    Returns pending tasks that have unresolved blocking dependencies.
    """
    tasks = task_store.list_blocked_tasks(project_id, limit=limit)
    return TaskListResponse(
        tasks=[_task_to_response(t) for t in tasks],
        total=len(tasks),
    )


@router.post("/projects/{project_id}/tasks", response_model=TaskResponse)
async def create_task(project_id: str, task: TaskCreate) -> TaskResponse:
    """Create a new task.

    If acceptance_criteria is provided, validates them using Opus.
    Returns 422 if any criteria fail validation.

    Args:
        project_id: Project ID
        task: Task data (title, description, priority, labels, task_type, etc.)
    """
    # Validate acceptance criteria if provided
    acceptance_criteria_dicts: list[dict] | None = None
    if task.acceptance_criteria:
        if not task.objective:
            raise HTTPException(
                status_code=422,
                detail="objective is required when acceptance_criteria is provided",
            )

        result = validate_criteria(task.objective, task.acceptance_criteria)
        if not result.valid:
            failure_details = [
                {"criterion_id": f.criterion_id, "issues": f.issues, "suggestion": f.suggestion}
                for f in result.failures
            ]
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "Acceptance criteria failed validation",
                    "failures": failure_details,
                },
            )

        # Convert to dicts for storage
        acceptance_criteria_dicts = [c.model_dump() for c in task.acceptance_criteria]

    created = task_store.create_task(
        project_id=project_id,
        title=task.title,
        description=task.description,
        capability_id=task.capability_id,
        priority=task.priority,
        labels=task.labels,
        task_type=task.task_type,
        parent_task_id=task.parent_task_id,
        objective=task.objective,
        acceptance_criteria=acceptance_criteria_dicts,
    )
    return _task_to_response(created)


@router.get("/projects/{project_id}/tasks/{task_id}", response_model=TaskResponse)
async def get_task(project_id: str, task_id: str) -> TaskResponse:
    """Get a single task by ID.

    Args:
        project_id: Project ID
        task_id: Task ID
    """
    task = _verify_task_project(task_id, project_id)
    return _task_to_response(task)


@router.patch("/projects/{project_id}/tasks/{task_id}", response_model=TaskResponse)
async def update_task(project_id: str, task_id: str, update: TaskUpdate) -> TaskResponse:
    """Update a task.

    Args:
        project_id: Project ID
        task_id: Task ID
        update: Fields to update
    """
    existing = _verify_task_project(task_id, project_id)

    update_fields = update.model_dump(exclude_unset=True)
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
    _verify_task_project(task_id, project_id)

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
        update: New status, optional error message, and force flag

    Note:
        When completing a task with acceptance_criteria, all criteria must have
        verified=true unless force=true.
    """
    task = _verify_task_project(task_id, project_id)

    # Validate acceptance criteria when completing (unless force=true)
    if update.status == "completed" and not update.force:
        acceptance_criteria = task.get("acceptance_criteria") or []
        if isinstance(acceptance_criteria, list) and acceptance_criteria:
            unverified = [
                crit.get("id", "unknown")
                for crit in acceptance_criteria
                if not crit.get("verified", False)
            ]
            if unverified:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "message": "Cannot complete task with unverified acceptance criteria",
                        "unverified_criteria": unverified,
                        "hint": "Use force=true to bypass this check",
                    },
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
    from ..tasks.agent_runner import run_agent_task

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


# Dependency endpoints
@router.get(
    "/projects/{project_id}/tasks/{task_id}/dependencies", response_model=list[DependencyResponse]
)
async def get_task_dependencies(project_id: str, task_id: str) -> list[DependencyResponse]:
    """Get dependencies for a task (what this task depends on).

    Args:
        project_id: Project ID
        task_id: Task ID

    Returns:
        List of dependencies with details about the blocking tasks.
    """
    _verify_task_project(task_id, project_id)

    deps = dep_store.get_dependencies(task_id)
    return [
        DependencyResponse(
            id=d["id"],
            task_id=d["task_id"],
            depends_on_task_id=d["depends_on_task_id"],
            dependency_type=d["dependency_type"],
            created_at=d["created_at"].isoformat() if d["created_at"] else None,
            depends_on_title=d.get("depends_on_title"),
            depends_on_status=d.get("depends_on_status"),
        )
        for d in deps
    ]


@router.post(
    "/projects/{project_id}/tasks/{task_id}/dependencies", response_model=DependencyResponse
)
async def add_task_dependency(
    project_id: str, task_id: str, dep: DependencyCreate
) -> DependencyResponse:
    """Add a dependency to a task.

    Args:
        project_id: Project ID
        task_id: Task ID (the task that depends on another)
        dep: Dependency details (depends_on_task_id, dependency_type)

    Returns:
        The created dependency.
    """
    _verify_task_project(task_id, project_id)

    # Verify target task exists
    target = task_store.get_task(dep.depends_on_task_id)
    if not target:
        raise HTTPException(
            status_code=404, detail=f"Target task {dep.depends_on_task_id} not found"
        )

    try:
        created = dep_store.add_dependency(
            task_id=task_id,
            depends_on_task_id=dep.depends_on_task_id,
            dependency_type=dep.dependency_type,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    if not created:
        raise HTTPException(status_code=400, detail="Failed to create dependency")

    return DependencyResponse(
        id=created["id"],
        task_id=created["task_id"],
        depends_on_task_id=created["depends_on_task_id"],
        dependency_type=created["dependency_type"],
        created_at=created["created_at"].isoformat() if created["created_at"] else None,
    )


@router.delete(
    "/projects/{project_id}/tasks/{task_id}/dependencies/{depends_on_task_id}",
    response_model=dict[str, Any],
)
async def remove_task_dependency(
    project_id: str,
    task_id: str,
    depends_on_task_id: str,
    dependency_type: str | None = Query(None, description="Type to remove (all if not specified)"),
) -> dict[str, Any]:
    """Remove a dependency from a task.

    Args:
        project_id: Project ID
        task_id: Task ID
        depends_on_task_id: ID of the task being depended on
        dependency_type: Optional type filter (removes all types if not specified)

    Returns:
        Status dict.
    """
    _verify_task_project(task_id, project_id)

    removed = dep_store.remove_dependency(task_id, depends_on_task_id, dependency_type)

    return {
        "status": "removed" if removed else "not_found",
        "task_id": task_id,
        "depends_on_task_id": depends_on_task_id,
        "dependency_type": dependency_type,
    }


# Task claim/release endpoints
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


@router.post(
    "/projects/{project_id}/tasks/criteria/validate",
    response_model=CriteriaValidateResponse,
)
async def validate_task_criteria(
    project_id: str, request: CriteriaValidateRequest
) -> CriteriaValidateResponse:
    """Validate acceptance criteria quality using Opus.

    Evaluates each criterion against quality checklist:
    - Specific: Concrete, unambiguous behavior
    - Measurable: Can be verified with yes/no answer
    - Testable: Can be verified by automated test
    - Threshold: Performance criteria have concrete values

    Args:
        project_id: Project ID (for future project-specific validation rules)
        request: Objective and criteria to validate

    Returns:
        Validation result with overall validity and per-criterion failures.
    """
    result = validate_criteria(request.objective, request.criteria)

    return CriteriaValidateResponse(
        valid=result.valid,
        failures=[
            CriterionFailure(
                criterion_id=f.criterion_id,
                valid=f.valid,
                issues=f.issues,
                suggestion=f.suggestion,
            )
            for f in result.failures
        ],
    )


@router.post(
    "/projects/{project_id}/tasks/{task_id}/criteria/{criterion_id}/verify",
    response_model=TaskResponse,
)
async def verify_criterion(
    project_id: str, task_id: str, criterion_id: str, request: CriterionVerifyRequest
) -> TaskResponse:
    """Mark a criterion as verified.

    Updates the matching criterion in acceptance_criteria with:
    - verified: true
    - verified_at: current timestamp
    - verified_by: value from request

    Args:
        project_id: Project ID
        task_id: Task ID
        criterion_id: Criterion ID (e.g., ac-001)
        request: Verification details (verified_by, optional notes)

    Returns:
        Updated task.

    Raises:
        HTTPException(404): Task or criterion not found
        HTTPException(400): Task has no acceptance_criteria
    """
    from datetime import UTC, datetime

    task = _verify_task_project(task_id, project_id)

    if not task.get("acceptance_criteria"):
        raise HTTPException(
            status_code=400,
            detail=f"Task {task_id} has no acceptance_criteria",
        )

    # Find and update the criterion
    criteria = task["acceptance_criteria"]
    found = False
    for criterion in criteria:
        if criterion.get("id") == criterion_id:
            criterion["verified"] = True
            criterion["verified_at"] = datetime.now(UTC).isoformat()
            criterion["verified_by"] = request.verified_by
            found = True
            break

    if not found:
        raise HTTPException(
            status_code=404,
            detail=f"Criterion {criterion_id} not found in task {task_id}",
        )

    # Update the task
    updated = task_store.update_task(task_id, acceptance_criteria=criteria)

    if not updated:
        raise HTTPException(status_code=500, detail="Failed to update task")

    return _task_to_response(updated)


@router.patch(
    "/projects/{project_id}/tasks/{task_id}/criteria/{criterion_id}/link-test",
    response_model=TaskResponse,
)
async def link_test_to_criterion(
    project_id: str, task_id: str, criterion_id: str, request: CriterionLinkTestRequest
) -> TaskResponse:
    """Link a test to a criterion.

    Updates the matching criterion with test_file and test_name.

    Args:
        project_id: Project ID
        task_id: Task ID
        criterion_id: Criterion ID (e.g., ac-001)
        request: Test file and function name

    Returns:
        Updated task.

    Raises:
        HTTPException(404): Task or criterion not found
        HTTPException(400): Task has no acceptance_criteria
    """
    task = _verify_task_project(task_id, project_id)

    if not task.get("acceptance_criteria"):
        raise HTTPException(
            status_code=400,
            detail=f"Task {task_id} has no acceptance_criteria",
        )

    # Find and update the criterion
    criteria = task["acceptance_criteria"]
    found = False
    for criterion in criteria:
        if criterion.get("id") == criterion_id:
            criterion["test_file"] = request.test_file
            criterion["test_name"] = request.test_name
            found = True
            break

    if not found:
        raise HTTPException(
            status_code=404,
            detail=f"Criterion {criterion_id} not found in task {task_id}",
        )

    # Update the task
    updated = task_store.update_task(task_id, acceptance_criteria=criteria)

    if not updated:
        raise HTTPException(status_code=500, detail="Failed to update task")

    return _task_to_response(updated)
