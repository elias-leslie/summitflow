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
from fastapi.responses import PlainTextResponse

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
from ...storage.steps import get_steps_for_subtask
from ...storage.subtasks import get_subtasks_for_task

logger = get_logger(__name__)

router = APIRouter()


def _get_step_count_for_task(task_id: str) -> int:
    """Get total step count across all subtasks for a task.

    Returns 0 if no subtasks or steps exist.
    """
    subtasks = get_subtasks_for_task(task_id, include_steps=False)
    if not subtasks:
        return 0

    total = 0
    for subtask in subtasks:
        steps = get_steps_for_subtask(subtask.get("id", ""))
        total += len(steps)
    return total


def _get_step_counts_batch(task_ids: list[str]) -> dict[str, int]:
    """Get step counts for multiple tasks.

    Returns dict mapping task_id to step count.
    """
    return {task_id: _get_step_count_for_task(task_id) for task_id in task_ids}


def _get_step_verification_status(task_id: str) -> dict[str, Any]:
    """Get step verification status for a task.

    Returns dict with:
    - total: int (total steps)
    - verified: int (passed steps, including plan_defect with completed fix)
    - unverified: list of step IDs that haven't passed
    - all_verified: bool
    """
    from ...storage.steps import STEP_STATUS_PLAN_DEFECT

    subtasks = get_subtasks_for_task(task_id, include_steps=False)
    if not subtasks:
        return {"total": 0, "verified": 0, "unverified": [], "all_verified": True}

    total = 0
    verified = 0
    unverified: list[str] = []

    for subtask in subtasks:
        subtask_id = subtask.get("id", "")
        steps = get_steps_for_subtask(subtask_id)
        for step in steps:
            total += 1
            step_id = f"{subtask_id}.{step.get('step_number', 0)}"
            if step.get("passes"):
                verified += 1
            elif step.get("status") == STEP_STATUS_PLAN_DEFECT and step.get("fix_step_number"):
                # Plan defect steps with linked fix step count as verified
                verified += 1
            else:
                unverified.append(step_id)

    return {
        "total": total,
        "verified": verified,
        "unverified": unverified,
        "all_verified": len(unverified) == 0,
    }


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


def _get_task_or_404(task_id: str) -> dict[str, Any]:
    """Get task by ID without project validation.

    Task IDs are globally unique, so project_id is not required.
    Use this for global endpoints where project context is not available.

    Args:
        task_id: Task ID to fetch

    Returns:
        Task dict

    Raises:
        HTTPException(404): If task not found
    """
    task = task_store.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return task


def _dispatch_autonomous_task(task_id: str, new_status: str, project_id: str) -> None:
    """Dispatch autonomous execution Celery task based on status transition.

    Status triggers:
    - pending -> Idea triage (if task_type is 'idea')
    - queue -> Begin autonomous execution
    - cancelled/blocked (from running) -> Emergency stop
    """
    try:
        if new_status == "queue":
            from ...tasks.autonomous import start_execution

            start_execution.delay(task_id, project_id)
            logger.info("Dispatched autonomous execution", task_id=task_id, status=new_status)

        elif new_status == "pending":
            task = task_store.get_task(task_id)
            if task and task.get("task_type") == "idea":
                from ...tasks.autonomous import triage_idea

                triage_idea.delay(task_id, project_id)
                logger.info("Dispatched idea triage", task_id=task_id)

        elif new_status in ("cancelled", "blocked"):
            _abort_running_task(task_id)

    except ImportError:
        logger.debug("Autonomous tasks not available")
    except Exception as e:
        logger.warning("Failed to dispatch autonomous task", task_id=task_id, error=str(e))


def _abort_running_task(task_id: str) -> None:
    """Emergency stop - abort any running Celery tasks for this task.

    Called when task is dragged out of running column (to cancelled/blocked).
    """
    try:
        from ...services.celery_inspector import revoke_task_by_name

        revoke_task_by_name(f"autonomous.start_execution:{task_id}")
        logger.info("Aborted running task", task_id=task_id)
    except ImportError:
        logger.debug("Celery inspector not available")
    except Exception as e:
        logger.warning("Failed to abort running task", task_id=task_id, error=str(e))


def _toon_format_task(task: TaskResponse) -> str:
    """Convert TaskResponse to TOON (Token-Optimized Output Notation) format.

    Format: ID|STATUS|PRIORITY|TYPE|COMPLEXITY|DONE/TOTAL|CRITERIA|DECISIONS|TITLE
    Example: task-abc123|running|P2|task|STANDARD|0/6|criteria:19|decisions:0|Add TOON format
    """
    # Calculate done/total from subtask_summary if available
    done_total = "0/0"
    if task.subtask_summary:
        done_total = f"{task.subtask_summary.completed}/{task.subtask_summary.total}"

    # Format criteria count
    criteria_str = f"criteria:{task.criteria_count or 0}"

    # Format decisions count
    decisions_count = len(task.decisions) if task.decisions else 0
    decisions_str = f"decisions:{decisions_count}"

    # Format priority
    priority_str = f"P{task.priority}"

    # Complexity (default to empty if not set)
    complexity_str = task.complexity or ""

    # Truncate title to 80 chars max
    title = task.title[:80] if task.title else ""

    return f"{task.id}|{task.status}|{priority_str}|{task.task_type}|{complexity_str}|{done_total}|{criteria_str}|{decisions_str}|{title}"


def toon_format(task: TaskResponse) -> str:
    """Public API for TOON formatting - alias for _toon_format_task."""
    return _toon_format_task(task)


def get_hints(tasks: list[TaskResponse], project_id: str, endpoint_type: str = "list") -> list[str]:
    """Generate navigation hints based on task state.

    Args:
        tasks: List of task responses
        project_id: Current project ID
        endpoint_type: Type of endpoint (list, ready, blocked)

    Returns:
        List of hint strings with API URLs for next actions
    """
    hints: list[str] = []
    base_url = f"http://localhost:8001/api/projects/{project_id}"

    if not tasks:
        hints.append(f"No tasks found. Create one: POST {base_url}/tasks")
        return hints

    # Count by status
    status_counts: dict[str, int] = {}
    for task in tasks:
        status_counts[task.status] = status_counts.get(task.status, 0) + 1

    # Suggest based on endpoint type and task states
    if endpoint_type == "ready":
        if tasks:
            first = tasks[0]
            hints.append(f"Full context: GET {base_url}/tasks/{first.id}/context")
            hints.append(f"Start task: PATCH {base_url}/tasks/{first.id}/status")
    elif endpoint_type == "blocked":
        hints.append(f"View ready tasks: GET {base_url}/tasks/ready")
        if tasks:
            first = tasks[0]
            hints.append(f"View blockers: GET {base_url}/tasks/{first.id}/dependencies")
    else:
        # General list hints - always include context hint first
        first = tasks[0]
        hints.append(f"Full context: GET {base_url}/tasks/{first.id}/context")
        if status_counts.get("pending", 0) > 0:
            hints.append(f"View ready tasks: GET {base_url}/tasks/ready")
        if status_counts.get("running", 0) > 0:
            hints.append(f"Filter running: GET {base_url}/tasks?status=running")
        if len(tasks) >= 50:
            hints.append(f"More results: GET {base_url}/tasks?offset=50")

    return hints


def _toon_format_task_list(tasks: list[TaskResponse], endpoint_type: str = "list") -> str:
    """Convert task list to TOON format.

    Format:
    ENDPOINT:PREFIX:TOTAL
    task lines...

    Example for ready endpoint:
    READY:3
    task-abc123|pending|P2|task|STANDARD|0/6|criteria:19|decisions:0|Add TOON format
    """
    prefix_map = {"ready": "READY", "blocked": "BLOCKED", "list": "TASKS"}

    prefix = prefix_map.get(endpoint_type, "TASKS")
    lines = [f"{prefix}:{len(tasks)}"]

    for task in tasks:
        lines.append(_toon_format_task(task))

    return "\n".join(lines)


def _task_to_response(task: dict[str, Any], criteria_count: int | None = None) -> TaskResponse:
    """Convert task dict to response model.

    Args:
        task: Task dict from storage
        criteria_count: Pre-fetched criteria count (avoids N+1 query in list endpoints)
    """
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
        criteria_count=criteria_count
        if criteria_count is not None
        else _get_step_count_for_task(task["id"]),
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
        # QA workflow fields (migration 068)
        qa_status=task.get("qa_status", "pending"),
        qa_signoff_at=task["qa_signoff_at"].isoformat() if task.get("qa_signoff_at") else None,
        qa_signoff_by=task.get("qa_signoff_by"),
        qa_issues=task.get("qa_issues"),
        # Plan workflow fields (from task_spirit if joined)
        plan_status=task.get("plan_status"),
        plan_approved_at=task.get("plan_approved_at"),
        plan_approved_by=task.get("plan_approved_by"),
        # Context for plan.json round-trip (from task_spirit if joined)
        context=task.get("context"),
    )


# Endpoints
@router.get("/projects/{project_id}/tasks", response_model=None)
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
    format: str | None = Query(
        None, description="Output format: 'toon' for compact token-optimized"
    ),
) -> TaskListResponse | PlainTextResponse:
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

    # Batch fetch criteria counts to avoid N+1 queries
    task_ids = [t["id"] for t in tasks]
    criteria_counts = _get_step_counts_batch(task_ids)

    task_responses = [_task_to_response(t, criteria_counts.get(t["id"], 0)) for t in tasks]

    # Return TOON format if requested
    if format == "toon":
        return PlainTextResponse(
            content=_toon_format_task_list(task_responses, endpoint_type="list")
        )

    return TaskListResponse(
        tasks=task_responses,
        total=len(tasks),  # TODO: Add proper total count
        hints=get_hints(task_responses, project_id, endpoint_type="list"),
    )


@router.get("/projects/{project_id}/tasks/ready", response_model=None)
async def list_ready_tasks(
    project_id: str,
    limit: int = Query(50, ge=1, le=500, description="Results per page"),
    format: str | None = Query(
        None, description="Output format: 'toon' for compact token-optimized"
    ),
) -> TaskListResponse | PlainTextResponse:
    """List tasks that are ready to work on (not blocked by dependencies).

    Returns pending tasks with no incomplete blocking dependencies,
    ordered by priority then creation date.
    """
    tasks = task_store.list_ready_tasks(project_id, limit=limit)

    # Batch fetch criteria counts to avoid N+1 queries
    task_ids = [t["id"] for t in tasks]
    criteria_counts = _get_step_counts_batch(task_ids)

    task_responses = [_task_to_response(t, criteria_counts.get(t["id"], 0)) for t in tasks]

    # Return TOON format if requested
    if format == "toon":
        return PlainTextResponse(
            content=_toon_format_task_list(task_responses, endpoint_type="ready")
        )

    return TaskListResponse(
        tasks=task_responses,
        total=len(tasks),
        hints=get_hints(task_responses, project_id, endpoint_type="ready"),
    )


@router.get("/projects/{project_id}/tasks/blocked", response_model=None)
async def list_blocked_tasks(
    project_id: str,
    limit: int = Query(50, ge=1, le=500, description="Results per page"),
    format: str | None = Query(
        None, description="Output format: 'toon' for compact token-optimized"
    ),
) -> TaskListResponse | PlainTextResponse:
    """List tasks that are blocked by incomplete dependencies.

    Returns pending tasks that have unresolved blocking dependencies.
    """
    tasks = task_store.list_blocked_tasks(project_id, limit=limit)

    # Batch fetch criteria counts to avoid N+1 queries
    task_ids = [t["id"] for t in tasks]
    criteria_counts = _get_step_counts_batch(task_ids)

    task_responses = [_task_to_response(t, criteria_counts.get(t["id"], 0)) for t in tasks]

    # Return TOON format if requested
    if format == "toon":
        return PlainTextResponse(
            content=_toon_format_task_list(task_responses, endpoint_type="blocked")
        )

    return TaskListResponse(
        tasks=task_responses,
        total=len(tasks),
        hints=get_hints(task_responses, project_id, endpoint_type="blocked"),
    )


@router.post("/projects/{project_id}/tasks", response_model=TaskResponse)
async def create_task(project_id: str, task: TaskCreate) -> TaskResponse:
    """Create a new task.

    Note: Acceptance criteria are now managed via task_criteria junction table.
    Use POST /projects/{project_id}/criteria to create criteria, then link via
    POST /projects/{project_id}/criteria/{criterion_id}/link-task.

    Args:
        project_id: Project ID
        task: Task data (title, description, priority, task_type, etc.)
    """
    from ...storage.task_spirit import upsert_task_spirit

    created = task_store.create_task(
        project_id=project_id,
        title=task.title,
        description=task.description,
        capability_id=task.capability_id,
        priority=task.priority,
        task_type=task.task_type,
        parent_task_id=task.parent_task_id,
        complexity=task.complexity,
    )

    # Save spirit fields to task_spirit table
    if task.objective or task.spirit_anti or task.decisions or task.constraints or task.done_when:
        upsert_task_spirit(
            task_id=created["id"],
            objective=task.objective or "",
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

    from ...storage.task_spirit import upsert_task_spirit

    for item in body.items:
        try:
            # Create task (basic fields only)
            task = task_store.create_task(
                project_id=project_id,
                title=item.title,
                description=item.description,
                capability_id=item.capability_id,
                priority=item.priority,
                task_type=item.task_type,
                parent_task_id=item.parent_task_id,
                complexity=item.complexity,
            )

            # Save spirit fields to task_spirit table
            if (
                item.objective
                or item.spirit_anti
                or item.decisions
                or item.constraints
                or item.done_when
            ):
                try:
                    upsert_task_spirit(
                        task_id=task["id"],
                        objective=item.objective or "",
                        spirit_anti=item.spirit_anti,
                        decisions=item.decisions,
                        constraints=item.constraints,
                        done_when=item.done_when,
                        complexity=item.complexity,
                    )
                except Exception as spirit_err:
                    logger.warning(
                        f"Failed to create task_spirit for task {task['id']}: {spirit_err}"
                    )

            # Create nested subtasks if provided
            created_subtasks = None
            if item.subtasks:
                try:
                    subtask_dicts = []
                    for s in item.subtasks:
                        # Convert StepInput models to dicts for storage layer
                        steps_as_dicts: list[str | dict[str, Any]] = []
                        for step in s.steps:
                            if isinstance(step, str):
                                steps_as_dicts.append(step)
                            else:
                                step_dict: dict[str, Any] = {"description": step.description}
                                if step.spec:
                                    step_dict["spec"] = step.spec
                                if step.verify_command:
                                    step_dict["verify_command"] = step.verify_command
                                if step.expected_output:
                                    step_dict["expected_output"] = step.expected_output
                                steps_as_dicts.append(step_dict)
                        subtask_dicts.append(
                            {
                                "subtask_id": s.subtask_id,
                                "phase": s.phase,
                                "description": s.description,
                                "steps": steps_as_dicts,
                                "display_order": s.display_order,
                                "details": s.details,
                            }
                        )
                    created_subtasks = bulk_create_subtasks(task["id"], subtask_dicts)

                    # Handle subtask dependencies
                    from ...storage.subtasks import bulk_add_subtask_dependencies

                    dependencies: list[tuple[str, str]] = []
                    for s in item.subtasks:
                        if s.depends_on:
                            for dep in s.depends_on:
                                dependencies.append((s.subtask_id, dep))
                    if dependencies:
                        try:
                            bulk_add_subtask_dependencies(task["id"], dependencies)
                        except Exception as dep_err:
                            logger.warning(  # type: ignore[call-arg]
                                "Failed to create dependencies for task %s: %s",
                                task["id"],
                                dep_err,
                            )
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


@router.get("/tasks/{task_id}", response_model=None)
async def get_task_global(
    task_id: str,
    format: str | None = Query(
        None, description="Output format: 'toon' for compact token-optimized"
    ),
) -> TaskResponse | PlainTextResponse:
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

    task_response = _task_to_response(task)

    # Return TOON format if requested
    if format == "toon":
        return PlainTextResponse(content=_toon_format_task(task_response))

    return task_response


@router.get("/projects/{project_id}/tasks/{task_id}", response_model=None)
async def get_task(
    project_id: str,
    task_id: str,
    format: str | None = Query(
        None, description="Output format: 'toon' for compact token-optimized"
    ),
) -> TaskResponse | PlainTextResponse:
    """Get a single task by ID.

    Args:
        project_id: Project ID
        task_id: Task ID
    """
    task = _verify_task_project(task_id, project_id)
    task_response = _task_to_response(task)

    # Return TOON format if requested
    if format == "toon":
        return PlainTextResponse(content=_toon_format_task(task_response))

    return task_response


@router.patch("/projects/{project_id}/tasks/{task_id}", response_model=TaskResponse)
async def update_task(project_id: str, task_id: str, update: TaskUpdate) -> TaskResponse:
    """Update a task.

    Args:
        project_id: Project ID
        task_id: Task ID
        update: Fields to update
    """
    from ...storage.task_spirit import update_task_spirit

    existing = _verify_task_project(task_id, project_id)

    update_fields = update.model_dump(exclude_unset=True)
    if not update_fields:
        return _task_to_response(existing)

    # Split into task fields and spirit fields
    spirit_fields = {"objective", "spirit_anti", "decisions", "constraints", "done_when", "labels"}
    task_updates = {k: v for k, v in update_fields.items() if k not in spirit_fields}
    spirit_updates = {
        k: v for k, v in update_fields.items() if k in spirit_fields and k != "labels"
    }

    # Update task table
    if task_updates:
        updated = task_store.update_task(task_id, **task_updates)
        if not updated:
            raise HTTPException(status_code=500, detail="Failed to update task")
    else:
        updated = existing

    # Update task_spirit table
    if spirit_updates:
        update_task_spirit(task_id, **spirit_updates)

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
    _verify_task_project(task_id, project_id)

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

        # Gate 2: Task must have at least one verified step
        # Note: Step verify_commands are run when marking steps as passed, not here
        step_status = _get_step_verification_status(task_id)

        # Gate 2a: Cannot complete task with zero steps (verification is mandatory)
        if step_status["total"] == 0:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "Cannot complete task with zero steps",
                    "total_steps": 0,
                    "what_to_do": [
                        "Every task must have at least one step with verify_command",
                        "Create subtasks with steps, or import a proper plan.json",
                    ],
                },
            )

        # Gate 2b: All steps must be verified
        if not step_status["all_verified"]:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "Cannot complete task with incomplete steps",
                    "unverified_steps": step_status["unverified"][:10],
                    "remaining": len(step_status["unverified"]),
                    "what_to_do": [
                        "Complete all steps before closing the task",
                        f"Run: st context {task_id} to see remaining steps",
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

    # Dispatch autonomous execution tasks on status transitions
    _dispatch_autonomous_task(task_id, update.status, project_id)

    # Populate verification_result on completion (step-level verification)
    if update.status == "completed" and updated:
        step_status = _get_step_verification_status(task_id)
        verification_result = {
            "total": step_status["total"],
            "verified": step_status["verified"],
            "unverified": step_status["unverified"],
            "all_verified": step_status["all_verified"],
        }
        updated = task_store.update_task(task_id, verification_result=verification_result)

    if updated is None:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return _task_to_response(updated)
