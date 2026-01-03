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

from ..constants import DEFAULT_GEMINI_MODEL, VALID_AGENT_TYPES
from ..logging_config import get_logger
from ..schemas.steps import (
    BatchStepCreate,
    BatchStepResponse,
    StepResponse,
    StepSummary,
    StepUpdate,
)
from ..schemas.tasks import (
    AcceptanceCriterion,
    BatchCriterionResult,
    BatchTaskCriteriaRequest,
    BatchTaskCriteriaResponse,
    BatchTaskRequest,
    BatchTaskResponse,
    BatchTaskResult,
    BlockerInfo,
    CapabilityContext,
    ClaimTaskRequest,
    CleanupPromptRequest,
    CleanupPromptResponse,
    CreateTaskCriterionRequest,
    CriteriaValidateRequest,
    CriteriaValidateResponse,
    CriterionFailure,
    DependencyCreate,
    DependencyResponse,
    DiscussionMessage,
    DiscussionRequest,
    DiscussionResponse,
    EnrichmentRequest,
    EnrichmentResponse,
    StartTaskRequest,
    SubtaskCreate,
    SubtaskResponse,
    SubtaskUpdate,
    TaskCreate,
    TaskListResponse,
    TaskLogEntry,
    TaskResponse,
    TaskStatusUpdate,
    TaskUpdate,
    ValidationResultResponse,
    VerifyTaskCriterionRequest,
)
from ..services.criteria_validator import validate_criteria
from ..services.task_validation import validate_task_ready
from ..storage import task_dependencies as dep_store
from ..storage import tasks as task_store
from ..storage.connection import get_connection
from ..storage.criteria import (
    create_criterion,
    get_effective_criteria,
    link_criterion_to_task,
    unlink_criterion_from_task,
    update_task_criterion_verification,
)
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

    Note: Acceptance criteria are now managed via task_criteria junction table.
    Use POST /projects/{project_id}/criteria to create criteria, then link via
    POST /projects/{project_id}/criteria/{criterion_id}/link-task.

    Args:
        project_id: Project ID
        task: Task data (title, description, priority, labels, task_type, etc.)
    """
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
    )
    return _task_to_response(created)


@router.post("/projects/{project_id}/tasks/batch", response_model=BatchTaskResponse)
async def batch_create_tasks(project_id: str, body: BatchTaskRequest) -> BatchTaskResponse:
    """Create multiple tasks in a single request.

    Handles partial failures: returns both created tasks and errors.
    Each task is created independently, so failures don't rollback successes.

    Supports nested subtasks: if item.subtasks is provided, bulk_create_subtasks
    is called automatically. Subtask steps are created in the normalized table.

    Note: This endpoint does NOT validate acceptance_criteria for batch creates.
    For tasks with acceptance criteria, use the single create endpoint.

    Args:
        project_id: Project ID
        body: List of tasks to create (with optional capability_id linkages)

    Returns:
        BatchTaskResponse with created tasks and any errors.
    """
    from ..storage.subtasks import bulk_create_subtasks

    created: list[TaskResponse] = []
    errors: list[BatchTaskResult] = []

    for item in body.items:
        try:
            task = task_store.create_task(
                project_id=project_id,
                title=item.title,
                description=item.description,
                capability_id=item.capability_id,
                priority=item.priority,
                labels=item.labels,
                task_type=item.task_type,
                parent_task_id=item.parent_task_id,
                objective=item.objective,
            )

            # Create nested subtasks if provided
            if item.subtasks:
                try:
                    subtask_dicts = [
                        {
                            "subtask_id": s.subtask_id,
                            "phase": s.phase,
                            "description": s.description,
                            "steps": s.steps,
                            "display_order": s.display_order,
                        }
                        for s in item.subtasks
                    ]
                    bulk_create_subtasks(task["id"], subtask_dicts)
                except Exception as e:
                    logger.warning(  # type: ignore[call-arg]
                        "Failed to create subtasks for task %s: %s", task["id"], e
                    )
                    # Continue - task succeeded, subtasks failed (partial success)

            created.append(_task_to_response(task))
        except Exception as e:
            error_msg = str(e)
            if "violates foreign key constraint" in error_msg.lower():
                if "capability_id" in error_msg.lower():
                    error_msg = f"Capability with id {item.capability_id} not found"
                elif "parent_task_id" in error_msg.lower():
                    error_msg = f"Parent task {item.parent_task_id} not found"
            errors.append(
                BatchTaskResult(
                    title=item.title,
                    success=False,
                    error=error_msg,
                )
            )

    return BatchTaskResponse(created=created, errors=errors)


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
        raise HTTPException(status_code=400, detail=str(e)) from None

    if not updated:
        raise HTTPException(status_code=500, detail="Failed to update task status")

    # Append completion reason to progress_log if provided
    if update.reason and update.status in ("completed", "cancelled"):
        updated = task_store.append_progress_log(task_id, f"Closed: {update.reason}")

    # Populate verification_result on completion
    if update.status == "completed" and updated:
        with get_connection() as conn:
            criteria = get_effective_criteria(conn, project_id, updated)
            verified_count = sum(1 for c in criteria if c.get("verified"))
            verification_result = {
                "total": len(criteria),
                "verified": verified_count,
                "unverified": [c.get("criterion_id") for c in criteria if not c.get("verified")],
                "all_verified": verified_count == len(criteria) if criteria else True,
            }
            updated = task_store.update_task(task_id, verification_result=verification_result)

    if updated is None:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
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


# =============================================================================
# Task Criteria Junction Table Endpoints
# =============================================================================


@router.post(
    "/projects/{project_id}/tasks/{task_id}/criteria",
    response_model=dict[str, Any],
)
async def create_task_criterion(
    project_id: str,
    task_id: str,
    request: CreateTaskCriterionRequest,
) -> dict[str, Any]:
    """Create a criterion and link it to a task.

    Creates a new entry in acceptance_criteria and links it via task_criteria.
    These are "standalone" criteria that exist only for this task.

    Args:
        project_id: Project ID
        task_id: Task ID
        request: Criterion details

    Returns:
        Created criterion with id and criterion_id.
    """
    _verify_task_project(task_id, project_id)

    with get_connection() as conn:
        # Create the criterion
        criterion = create_criterion(
            conn=conn,
            project_id=project_id,
            criterion=request.criterion,
            category=request.category,
            measurement=request.measurement,
            threshold=request.threshold,
            created_by_task_id=task_id,
        )

        # Link to task
        link_criterion_to_task(conn, task_id, criterion["id"])

        logger.info(
            "task_criterion_created",
            task_id=task_id,
            criterion_id=criterion["criterion_id"],
        )

    return {
        "id": criterion["id"],
        "criterion_id": criterion["criterion_id"],
        "criterion": criterion["criterion"],
        "category": criterion["category"],
        "measurement": criterion["measurement"],
        "threshold": criterion["threshold"],
        "task_id": task_id,
    }


@router.delete(
    "/projects/{project_id}/tasks/{task_id}/criteria/{criterion_id}",
    response_model=dict[str, Any],
)
async def delete_task_criterion(
    project_id: str,
    task_id: str,
    criterion_id: str,
) -> dict[str, Any]:
    """Unlink a criterion from a task.

    Removes the link from task_criteria. If criterion becomes orphaned
    (no links in capability_criteria or task_criteria), it's deleted.

    Args:
        project_id: Project ID
        task_id: Task ID
        criterion_id: Criterion ID (format: ac-NNN)

    Returns:
        Status dict.
    """
    from ..storage.criteria import get_criterion

    _verify_task_project(task_id, project_id)

    with get_connection() as conn:
        criterion = get_criterion(conn, project_id, criterion_id)
        if not criterion:
            raise HTTPException(
                status_code=404,
                detail=f"Criterion {criterion_id} not found",
            )

        removed = unlink_criterion_from_task(conn, task_id, criterion["id"])

    return {
        "status": "removed" if removed else "not_found",
        "task_id": task_id,
        "criterion_id": criterion_id,
    }


@router.post(
    "/projects/{project_id}/tasks/{task_id}/criteria/batch",
    response_model=BatchTaskCriteriaResponse,
    status_code=201,
)
async def batch_create_task_criteria(
    project_id: str,
    task_id: str,
    request: BatchTaskCriteriaRequest,
) -> BatchTaskCriteriaResponse:
    """Create multiple criteria and link them to a task in batch.

    Handles partial failures: returns both created criteria and errors.
    Each criterion is created independently, so failures don't rollback successes.

    Args:
        project_id: Project ID
        task_id: Task ID
        request: List of criteria to create

    Returns:
        BatchTaskCriteriaResponse with created criteria and any errors.
    """
    _verify_task_project(task_id, project_id)

    created: list[dict[str, Any]] = []
    errors: list[BatchCriterionResult] = []

    with get_connection() as conn:
        for item in request.items:
            try:
                # Create the criterion
                criterion = create_criterion(
                    conn=conn,
                    project_id=project_id,
                    criterion=item.criterion,
                    category=item.category,
                    measurement=item.measurement,
                    threshold=item.threshold,
                    created_by_task_id=task_id,
                )

                # Link to task
                link_criterion_to_task(conn, task_id, criterion["id"])

                created.append(
                    {
                        "id": criterion["id"],
                        "criterion_id": criterion["criterion_id"],
                        "criterion": criterion["criterion"],
                        "category": criterion["category"],
                        "measurement": criterion["measurement"],
                        "threshold": criterion["threshold"],
                        "task_id": task_id,
                    }
                )

                logger.info(
                    "batch_task_criterion_created",
                    task_id=task_id,
                    criterion_id=criterion["criterion_id"],
                )
            except Exception as e:
                errors.append(
                    BatchCriterionResult(
                        criterion=item.criterion[:50],
                        success=False,
                        error=str(e),
                    )
                )

    return BatchTaskCriteriaResponse(created=created, errors=errors)


@router.patch(
    "/projects/{project_id}/tasks/{task_id}/criteria/{criterion_id}/verify",
    response_model=dict[str, Any],
)
async def verify_task_criterion_junction(
    project_id: str,
    task_id: str,
    criterion_id: str,
    request: VerifyTaskCriterionRequest,
) -> dict[str, Any]:
    """Update verification status for a task's criterion.

    Updates the verified/verified_at/verified_by fields in task_criteria.

    Args:
        project_id: Project ID
        task_id: Task ID
        criterion_id: Criterion ID (format: ac-NNN)
        request: Verification details

    Returns:
        Status dict with updated verification info.
    """
    from ..storage.criteria import get_criterion

    _verify_task_project(task_id, project_id)

    with get_connection() as conn:
        criterion = get_criterion(conn, project_id, criterion_id)
        if not criterion:
            raise HTTPException(
                status_code=404,
                detail=f"Criterion {criterion_id} not found",
            )

        updated = update_task_criterion_verification(
            conn=conn,
            task_id=task_id,
            criterion_db_id=criterion["id"],
            verified=request.verified,
            verified_by=request.verified_by,
        )

        if not updated:
            raise HTTPException(
                status_code=404,
                detail=f"Criterion {criterion_id} not linked to task {task_id}",
            )

    return {
        "status": "verified" if request.verified else "unverified",
        "task_id": task_id,
        "criterion_id": criterion_id,
        "verified_by": request.verified_by,
    }


# =============================================================================
# Task Enrichment Endpoints
# =============================================================================


@router.post(
    "/projects/{project_id}/tasks/enrich",
    response_model=EnrichmentResponse,
    status_code=202,
)
async def enrich_task_endpoint(
    project_id: str,
    request: EnrichmentRequest,
    sync: bool = Query(default=False, description="Run enrichment synchronously"),
) -> EnrichmentResponse:
    """Create a task and trigger AI enrichment.

    Args:
        project_id: Project ID
        request: Enrichment request with raw_request text
        sync: If true, run enrichment inline (slower but returns enriched task)

    Returns:
        EnrichmentResponse with task_id and status
    """
    # Create task in draft state
    task = task_store.create_task(
        project_id=project_id,
        title=request.raw_request[:100] + ("..." if len(request.raw_request) > 100 else ""),
        raw_request=request.raw_request,
        enrichment_status="enriching" if not sync else "draft",
        priority=request.priority or 2,
        task_type=request.task_type or "task",
    )

    if sync:
        # Run enrichment synchronously
        try:
            from ..services.enrichment_service import apply_enrichment_to_task, enrich_and_validate

            enriched, _validation = enrich_and_validate(
                project_id=project_id,
                task_id=task["id"],
                raw_request=request.raw_request,
            )
            apply_enrichment_to_task(task["id"], enriched)

            return EnrichmentResponse(
                task_id=task["id"],
                enrichment_status="review",
                message="Task enriched successfully. Ready for review.",
            )
        except Exception as e:
            logger.error("Sync enrichment failed: %s", e)  # type: ignore[call-arg]
            task_store.update_task(task["id"], enrichment_status="failed")
            raise HTTPException(status_code=500, detail=f"Enrichment failed: {e}") from None
    else:
        # Queue for async enrichment
        try:
            from ..tasks.enrichment import enrich_task_async

            enrich_task_async.delay(project_id, task["id"], request.raw_request)
        except Exception as e:
            logger.warning("Failed to queue enrichment task: %s", e)  # type: ignore[call-arg]
            # Still return - we can retry later

        return EnrichmentResponse(
            task_id=task["id"],
            enrichment_status="enriching",
            message="Task created and enrichment queued.",
        )


@router.post(
    "/projects/{project_id}/tasks/{task_id}/discuss",
    response_model=DiscussionResponse,
)
async def discuss_task_endpoint(
    project_id: str,
    task_id: str,
    request: DiscussionRequest,
) -> DiscussionResponse:
    """Have a discussion about a task with AI.

    Args:
        project_id: Project ID
        task_id: Task ID to discuss
        request: Discussion request with message

    Returns:
        DiscussionResponse with AI reply and any updates
    """
    task = _verify_task_project(task_id, project_id)

    from ..services.enrichment_service import apply_discussion_changes, discuss_task

    # Get discussion history from task metadata (if any)
    history: list[dict[str, str]] = []
    plan_content = task.get("plan_content") or {}
    if "discussion_history" in plan_content:
        history = plan_content["discussion_history"]

    # Run discussion
    result = discuss_task(
        project_id=project_id,
        task_id=task_id,
        message=request.message,
        history=history,
        current_task=task,
    )

    # Update history
    history.append({"role": "user", "content": request.message})
    history.append({"role": "assistant", "content": result.response})

    # Apply changes if any
    updated_task = task
    if result.updated_task:
        updated_task = apply_discussion_changes(task_id, result.updated_task)

    # Store updated history
    plan_content["discussion_history"] = history
    task_store.update_task(task_id, plan_content=plan_content)

    # Update enrichment status if first message
    if task.get("enrichment_status") == "review":
        task_store.update_task(task_id, enrichment_status="discussing")

    return DiscussionResponse(
        response=result.response,
        updated_task=_task_to_response(updated_task) if result.updated_task else None,
        history=[
            DiscussionMessage(role=h["role"], content=h["content"], timestamp="") for h in history
        ],  # type: ignore[arg-type]
    )


@router.post(
    "/projects/{project_id}/tasks/{task_id}/accept",
    response_model=TaskResponse,
)
async def accept_task_endpoint(
    project_id: str,
    task_id: str,
) -> TaskResponse:
    """Accept an enriched task and mark it ready for execution.

    Args:
        project_id: Project ID
        task_id: Task ID to accept

    Returns:
        Updated TaskResponse
    """
    task = _verify_task_project(task_id, project_id)

    # Verify task is in acceptable state
    current_status = task.get("enrichment_status")
    if current_status not in ("review", "discussing"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot accept task with enrichment_status '{current_status}'. Must be 'review' or 'discussing'.",
        )

    # Update task
    updated = task_store.update_task(
        task_id,
        enrichment_status="accepted",
        status="pending",  # Ready for execution
    )

    if updated is None:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    return _task_to_response(updated)


@router.get(
    "/projects/{project_id}/tasks/{task_id}/subtasks",
    response_model=dict[str, Any],
)
async def get_task_subtasks(
    project_id: str,
    task_id: str,
    include_steps: bool = Query(False, description="Include steps from table for each subtask"),
) -> dict[str, Any]:
    """Get subtasks for a task.

    Args:
        project_id: Project ID
        task_id: Task ID
        include_steps: If True, include steps from task_subtask_steps table

    Returns:
        Dict with subtasks list and summary
    """
    _verify_task_project(task_id, project_id)

    from ..storage.subtasks import get_subtask_summary, get_subtasks_for_task

    subtasks = get_subtasks_for_task(task_id, include_steps=include_steps)
    summary = get_subtask_summary(task_id)

    return {
        "subtasks": subtasks,
        "summary": summary,
    }


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
    """Update a subtask's passes status.

    Args:
        project_id: Project ID
        task_id: Task ID
        subtask_id: Subtask ID (e.g., "1.1")
        request: Update with passes boolean

    Returns:
        Updated SubtaskResponse
    """
    _verify_task_project(task_id, project_id)

    from ..storage.subtasks import update_subtask_passes

    updated = update_subtask_passes(task_id, subtask_id, request.passes)

    if updated is None:
        raise HTTPException(
            status_code=404,
            detail=f"Subtask {subtask_id} not found for task {task_id}",
        )

    return SubtaskResponse(**updated)


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
    """Create a single subtask for a task.

    Args:
        project_id: Project ID
        task_id: Task ID
        request: Subtask creation data

    Returns:
        Created SubtaskResponse
    """
    _verify_task_project(task_id, project_id)

    from ..storage.subtasks import create_subtask

    subtask = create_subtask(
        task_id=task_id,
        subtask_id=request.subtask_id,
        description=request.description,
        display_order=request.display_order,
        phase=request.phase,
        steps=request.steps,
    )

    return SubtaskResponse(**subtask)


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
    """Create multiple subtasks for a task in batch.

    Args:
        project_id: Project ID
        task_id: Task ID
        request: {"items": [subtask_data_list]}

    Returns:
        {"created": list of created subtasks}
    """
    _verify_task_project(task_id, project_id)

    from ..storage.subtasks import bulk_create_subtasks

    items = request.get("items", [])
    if not items:
        return {"created": []}

    created = bulk_create_subtasks(task_id, items)

    return {"created": created}


@router.post(
    "/projects/{project_id}/tasks/cleanup-prompt",
    response_model=CleanupPromptResponse,
)
async def cleanup_prompt_endpoint(
    project_id: str,
    request: CleanupPromptRequest,
) -> CleanupPromptResponse:
    """Clean up and refine a raw prompt using AI.

    Uses Gemini Flash for fast, cheap text cleanup.

    Args:
        project_id: Project ID
        request: Request with raw_request text

    Returns:
        CleanupPromptResponse with cleaned text and changes list
    """
    try:
        from ..services.agents.gemini import GeminiClient

        client = GeminiClient(model=DEFAULT_GEMINI_MODEL)
        if not client.is_available():
            # Return unchanged if Gemini unavailable
            return CleanupPromptResponse(
                cleaned_prompt=request.raw_request,
                changes_made=["Gemini unavailable - no changes made"],
            )

        prompt = f"""Clean up and refine this task request. Fix grammar, clarify intent, and expand abbreviations. Keep the meaning unchanged.

Original:
{request.raw_request}

Return JSON:
{{"cleaned_prompt": "...", "changes_made": ["change1", "change2"]}}"""

        response = client.generate(prompt, max_tokens=1000, temperature=0.2)

        import json

        text = response.content.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]

        data = json.loads(text.strip())

        return CleanupPromptResponse(
            cleaned_prompt=data.get("cleaned_prompt", request.raw_request),
            changes_made=data.get("changes_made", []),
        )

    except Exception as e:
        logger.warning("Cleanup prompt failed: %s", e)  # type: ignore[call-arg]
        return CleanupPromptResponse(
            cleaned_prompt=request.raw_request,
            changes_made=[f"Cleanup failed: {e}"],
        )


# =============================================================================
# Step Endpoints (task_subtask_steps table)
# =============================================================================


def _get_subtask_table_id(task_id: str, subtask_id: str) -> str:
    """Generate the subtask table ID.

    Format: {task_id}-{subtask_id} e.g., "task-abc123-1.1"
    """
    return f"{task_id}-{subtask_id}"


@router.get(
    "/projects/{project_id}/tasks/{task_id}/subtasks/{subtask_id}/steps",
    response_model=list[StepResponse],
)
async def get_subtask_steps(
    project_id: str,
    task_id: str,
    subtask_id: str,
) -> list[StepResponse]:
    """Get steps for a subtask.

    Args:
        project_id: Project ID
        task_id: Task ID
        subtask_id: Subtask ID (e.g., "1.1")

    Returns:
        List of steps ordered by step_number
    """
    _verify_task_project(task_id, project_id)

    from ..storage.steps import get_steps_for_subtask

    table_id = _get_subtask_table_id(task_id, subtask_id)
    steps = get_steps_for_subtask(table_id)

    return [StepResponse(**s) for s in steps]


@router.post(
    "/projects/{project_id}/tasks/{task_id}/subtasks/{subtask_id}/steps/batch",
    response_model=BatchStepResponse,
    status_code=201,
)
async def create_steps_batch(
    project_id: str,
    task_id: str,
    subtask_id: str,
    request: BatchStepCreate,
) -> BatchStepResponse:
    """Create multiple steps for a subtask in batch.

    Steps are automatically numbered starting from 1.

    Args:
        project_id: Project ID
        task_id: Task ID
        subtask_id: Subtask ID (e.g., "1.1")
        request: List of step descriptions

    Returns:
        Created steps with count
    """
    _verify_task_project(task_id, project_id)

    from ..storage.steps import bulk_create_steps

    table_id = _get_subtask_table_id(task_id, subtask_id)

    try:
        created = bulk_create_steps(table_id, request.descriptions)
    except Exception as e:
        error_msg = str(e)
        if "violates foreign key constraint" in error_msg.lower():
            raise HTTPException(
                status_code=404,
                detail=f"Subtask {subtask_id} not found for task {task_id}",
            ) from None
        raise HTTPException(status_code=500, detail=error_msg) from None

    return BatchStepResponse(
        created=[StepResponse(**s) for s in created],
        count=len(created),
    )


@router.post(
    "/projects/{project_id}/tasks/{task_id}/subtasks/{subtask_id}/steps/append",
    response_model=BatchStepResponse,
    status_code=201,
)
async def append_steps_to_subtask(
    project_id: str,
    task_id: str,
    subtask_id: str,
    request: BatchStepCreate,
) -> BatchStepResponse:
    """Append steps to a subtask, continuing from the highest existing step number.

    Unlike /steps/batch which starts at 1, this finds the max step_number
    and continues from there. Safe to call on subtasks with existing steps.

    Args:
        project_id: Project ID
        task_id: Task ID
        subtask_id: Subtask ID (e.g., "1.1")
        request: List of step descriptions to append

    Returns:
        BatchStepResponse with created steps.
    """
    _verify_task_project(task_id, project_id)

    from ..storage.steps import append_steps

    table_id = _get_subtask_table_id(task_id, subtask_id)

    try:
        created = append_steps(table_id, request.descriptions)
    except Exception as e:
        error_msg = str(e)
        if "violates foreign key constraint" in error_msg.lower():
            raise HTTPException(
                status_code=404,
                detail=f"Subtask {subtask_id} not found for task {task_id}",
            ) from None
        raise HTTPException(status_code=500, detail=error_msg) from None

    return BatchStepResponse(
        created=[StepResponse(**s) for s in created],
        count=len(created),
    )


@router.patch(
    "/projects/{project_id}/tasks/{task_id}/subtasks/{subtask_id}/steps/{step_number}",
    response_model=StepResponse,
)
async def update_step(
    project_id: str,
    task_id: str,
    subtask_id: str,
    step_number: int,
    request: StepUpdate,
) -> StepResponse:
    """Update a step's passes status.

    Args:
        project_id: Project ID
        task_id: Task ID
        subtask_id: Subtask ID (e.g., "1.1")
        step_number: Step number (1-indexed)
        request: Update with passes boolean

    Returns:
        Updated step
    """
    _verify_task_project(task_id, project_id)

    from ..storage.steps import update_step_passes

    table_id = _get_subtask_table_id(task_id, subtask_id)
    updated = update_step_passes(table_id, step_number, request.passes)

    if updated is None:
        raise HTTPException(
            status_code=404,
            detail=f"Step {step_number} not found for subtask {subtask_id}",
        )

    return StepResponse(**updated)


@router.get(
    "/projects/{project_id}/tasks/{task_id}/subtasks/{subtask_id}/steps/summary",
    response_model=StepSummary,
)
async def get_step_summary_endpoint(
    project_id: str,
    task_id: str,
    subtask_id: str,
) -> StepSummary:
    """Get step completion summary for a subtask.

    Args:
        project_id: Project ID
        task_id: Task ID
        subtask_id: Subtask ID (e.g., "1.1")

    Returns:
        Summary with total, completed, progress_percent
    """
    _verify_task_project(task_id, project_id)

    from ..storage.steps import get_step_summary

    table_id = _get_subtask_table_id(task_id, subtask_id)
    summary = get_step_summary(table_id)

    return StepSummary(**summary)
