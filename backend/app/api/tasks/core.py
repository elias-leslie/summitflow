"""Tasks API - Core CRUD operations.

Handles:
- list_tasks, list_ready_tasks, list_blocked_tasks
- create_task, batch_create_tasks
- get_task, get_task_global
- update_task, update_task_status
- delete_task
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from ...logging_config import get_logger
from ...schemas.tasks import (
    AcceptanceCriterion,
    BatchTaskRequest,
    BatchTaskResponse,
    BatchTaskResult,
    BlockerInfo,
    CapabilityContext,
    SubtaskResponse,
    SubtaskSummary,
    TaskCreate,
    TaskListResponse,
    TaskResponse,
    TaskStatusUpdate,
    TaskUpdate,
)
from ...storage import task_dependencies as dep_store
from ...storage import tasks as task_store
from ...storage.connection import get_connection
from ...storage.criteria import get_criteria_count_for_task, get_effective_criteria

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

    # Handle subtask summary (from list_ready_tasks with JOIN)
    subtask_summary_obj = None
    if task.get("subtask_summary") is not None:
        ss = task["subtask_summary"]
        subtask_summary_obj = SubtaskSummary(
            total=ss.get("total", 0),
            completed=ss.get("completed", 0),
            next_subtask_id=ss.get("next_subtask_id"),
            progress_percent=ss.get("progress_percent", 0.0),
        )

    # Handle subtasks (from batch create with nested subtasks)
    subtasks_list = None
    if task.get("subtasks") is not None:

        def _format_datetime(val: Any) -> str | None:
            """Convert datetime to ISO string, handling already-string values."""
            if val is None:
                return None
            if isinstance(val, str):
                return val
            return val.isoformat() if hasattr(val, "isoformat") else str(val)

        subtasks_list = [
            SubtaskResponse(
                id=s["id"],
                task_id=s["task_id"],
                subtask_id=s["subtask_id"],
                phase=s.get("phase"),
                description=s["description"],
                # Steps from storage: list of dicts with "description" key
                steps=[step["description"] for step in s.get("steps", [])]
                if s.get("steps") and isinstance(s["steps"][0], dict)
                else s.get("steps", []),
                passes=s.get("passes", False),
                passed_at=_format_datetime(s.get("passed_at")),
                display_order=s.get("display_order", 0),
                created_at=_format_datetime(s.get("created_at")),
            )
            for s in task["subtasks"]
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
        criteria_count=get_criteria_count_for_task(task["id"]),
        current_phase=task.get("current_phase"),
        verification_result=task.get("verification_result"),
        # Pipeline v2 fields
        spirit_anti=task.get("spirit_anti"),
        decisions=task.get("decisions"),
        constraints=task.get("constraints"),
        done_when=task.get("done_when"),
        complexity=task.get("complexity"),
        # Optional feature context
        capability=capability_context,
        # Optional blockers context
        blockers=blockers_list,
        blocked_by_incomplete=blocked_by_incomplete,
        # Subtask summary (from list_ready_tasks with JOIN)
        subtask_summary=subtask_summary_obj,
        # Subtasks with steps (from batch create)
        subtasks=subtasks_list,
        # Autonomous execution flag
        autonomous=task.get("autonomous", False),
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
        # Pipeline v2 fields
        spirit_anti=task.spirit_anti,
        decisions=task.decisions,
        constraints=task.constraints,
        done_when=task.done_when,
        complexity=task.complexity,
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
    from ...storage.subtasks import bulk_create_subtasks

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
                # Pipeline v2 fields
                spirit_anti=item.spirit_anti,
                decisions=item.decisions,
                constraints=item.constraints,
                done_when=item.done_when,
                complexity=item.complexity,
            )

            # Create nested subtasks if provided
            created_subtasks = None
            if item.subtasks:
                try:
                    subtask_dicts = [
                        {
                            "subtask_id": s.subtask_id,
                            "phase": s.phase,
                            "description": s.description,
                            "steps": s.steps,
                            "display_order": s.display_order,
                            "details": s.details,
                        }
                        for s in item.subtasks
                    ]
                    created_subtasks = bulk_create_subtasks(task["id"], subtask_dicts)
                except Exception as e:
                    logger.warning(  # type: ignore[call-arg]
                        "Failed to create subtasks for task %s: %s", task["id"], e
                    )
                    # Continue - task succeeded, subtasks failed (partial success)

            # Include subtasks in response if created
            if created_subtasks:
                task["subtasks"] = created_subtasks

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


@router.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_task_global(task_id: str) -> TaskResponse:
    """Get a task by ID without requiring project context.

    Task IDs are globally unique, so project_id is not needed for lookup.
    This endpoint is useful for CLI tools that know the task ID but not
    the project context.

    Args:
        task_id: Task ID (e.g., "task-abc12345")
    """
    task = task_store.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return _task_to_response(task)


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
        update: New status and optional error message

    Note:
        When completing a task, all subtasks must be complete and all
        acceptance criteria must be verified. There is no bypass.
    """
    task = _verify_task_project(task_id, project_id)

    # Gate checks when completing - NO BYPASS ALLOWED
    # These gates ensure work is actually done before marking complete
    if update.status == "completed":
        # Gate 1: All subtasks must be complete
        from ...storage.subtasks import get_subtasks_for_task

        subtasks = get_subtasks_for_task(task_id)
        incomplete_subtasks = [s["subtask_id"] for s in subtasks if not s.get("passes")]
        if incomplete_subtasks:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "Cannot complete task with incomplete subtasks",
                    "incomplete_subtasks": incomplete_subtasks,
                    "what_to_do": [
                        f"Complete subtask {s} using: st subtask pass {task_id} {s}"
                        for s in incomplete_subtasks[:5]  # Show first 5
                    ],
                    "remaining": len(incomplete_subtasks),
                },
            )

        # Gate 2: All acceptance criteria must be verified (from all sources)
        with get_connection() as conn:
            criteria = get_effective_criteria(conn, project_id, task)
            if criteria:
                unverified = [
                    c.get("criterion_id", "unknown")
                    for c in criteria
                    if not c.get("verified", False)
                ]
                if unverified:
                    raise HTTPException(
                        status_code=422,
                        detail={
                            "message": "Cannot complete task with unverified acceptance criteria",
                            "unverified_criteria": unverified,
                            "what_to_do": [
                                "Verify each criterion by running its linked test",
                                "Use: st criterion verify <criterion-id> --by test",
                                "Or if verified externally: st criterion verify <criterion-id> --manual 'evidence'",
                            ],
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
