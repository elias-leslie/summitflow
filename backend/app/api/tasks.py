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
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..logging_config import get_logger
from ..services.task_validation import validate_task_ready
from ..storage import task_dependencies as dep_store
from ..storage import tasks as task_store

logger = get_logger(__name__)

router = APIRouter()


# Pydantic models for request/response
class TaskCreate(BaseModel):
    """Request model for creating a new task."""

    title: str
    description: str | None = None
    capability_id: int | None = None  # Database ID of capability (optional)
    # Issue tracking fields
    priority: int = Field(default=2, ge=0, le=4, description="Priority 0-4 (0=critical, 4=backlog)")
    labels: list[str] = Field(
        default_factory=list, description="Labels (complexity:small, domains:backend)"
    )
    task_type: Literal["feature", "bug", "task"] = "task"
    parent_task_id: str | None = None


class TaskUpdate(BaseModel):
    """Request model for updating a task."""

    title: str | None = None
    description: str | None = None
    branch_name: str | None = None
    pull_request_url: str | None = None
    # Issue tracking fields
    priority: int | None = Field(default=None, ge=0, le=4)
    labels: list[str] | None = None
    task_type: Literal["feature", "bug", "task"] | None = None
    parent_task_id: str | None = None


class TaskStatusUpdate(BaseModel):
    """Request model for updating task status."""

    status: str  # pending, running, paused, failed, completed
    error_message: str | None = None
    force: bool = False  # Bypass criteria validation on close


class TaskLogEntry(BaseModel):
    """Request model for appending to progress log."""

    entry: str


class DependencyCreate(BaseModel):
    """Request model for creating a dependency."""

    depends_on_task_id: str
    dependency_type: Literal["blocks", "discovered-from"] = "blocks"


class ValidationResultResponse(BaseModel):
    """Response model for task validation result."""

    ready: bool
    issues: list[str]
    suggestions: list[str]


class DependencyResponse(BaseModel):
    """Response model for a dependency."""

    id: int
    task_id: str
    depends_on_task_id: str
    dependency_type: str
    created_at: str | None
    depends_on_title: str | None = None
    depends_on_status: str | None = None


class AcceptanceCriterion(BaseModel):
    """Acceptance criterion for a feature."""

    id: str
    description: str
    passes: bool = False


class CapabilityContext(BaseModel):
    """Capability context for a task."""

    id: int  # Database ID
    capability_id: str  # String ID like login, password-reset
    name: str
    criteria_passed: int
    criteria_total: int
    acceptance_criteria: list[AcceptanceCriterion] | None = None


class BlockerInfo(BaseModel):
    """Information about a blocking task."""

    id: str
    title: str
    status: str
    priority: int


class TaskResponse(BaseModel):
    """Response model for a task."""

    id: str
    project_id: str
    capability_id: int | None
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
    # Issue tracking fields
    priority: int
    labels: list[str]
    task_type: str
    parent_task_id: str | None
    # Optional capability context (when include=capability)
    capability: CapabilityContext | None = None
    # Optional blockers context (when include=blockers)
    blockers: list[BlockerInfo] | None = None
    blocked_by_incomplete: bool | None = None


class TaskListResponse(BaseModel):
    """Response model for list of tasks."""

    tasks: list[TaskResponse]
    total: int


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
                    id=crit.get("id", ""),
                    description=crit.get("description", ""),
                    passes=crit.get("passes", False),
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
    include_capability = "capability" in includes
    include_blockers = "blockers" in includes

    tasks = task_store.list_tasks(
        project_id,
        status_filter=status,
        task_type_filter=task_type,
        priority_filter=priority,
        labels_filter=labels_list,
        orphans_only=orphans_only,
        include_capability=include_capability,
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
    # Issue tracking fields
    if update.priority is not None:
        update_fields["priority"] = update.priority
    if update.labels is not None:
        update_fields["labels"] = update.labels
    if update.task_type is not None:
        update_fields["task_type"] = update.task_type
    if update.parent_task_id is not None:
        update_fields["parent_task_id"] = update.parent_task_id

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
        update: New status, optional error message, and force flag

    Note:
        When completing a feature-type task linked to a feature with acceptance
        criteria, all criteria must pass unless force=true.
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
    # Verify task exists and belongs to project
    task = task_store.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    if task["project_id"] != project_id:
        raise HTTPException(
            status_code=404, detail=f"Task {task_id} not found in project {project_id}"
        )

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
    # Verify task exists and belongs to project
    task = task_store.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    if task["project_id"] != project_id:
        raise HTTPException(
            status_code=404, detail=f"Task {task_id} not found in project {project_id}"
        )

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
    # Verify task exists and belongs to project
    task = task_store.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    if task["project_id"] != project_id:
        raise HTTPException(
            status_code=404, detail=f"Task {task_id} not found in project {project_id}"
        )

    removed = dep_store.remove_dependency(task_id, depends_on_task_id, dependency_type)

    return {
        "status": "removed" if removed else "not_found",
        "task_id": task_id,
        "depends_on_task_id": depends_on_task_id,
        "dependency_type": dependency_type,
    }
