"""Autonomous work pickup and review tasks.

Supports two dispatch modes:
1. Event-driven: Immediate pickup via Redis pub/sub (from st autocode)
2. Polling: Fallback Beat task that checks every 2 hours for missed tasks

The event-driven path is preferred for low-latency dispatch.

Worktree Isolation:
When dispatching tasks to execution, a worktree is created at
~/.local/share/st/worktrees/<project-id>/<task-id>/ with branch <task-id>/main.
This ensures each task runs in isolation without affecting the main branch.
"""

from __future__ import annotations

from collections.abc import Callable

from app.logging_config import get_logger
from app.services.task_validation import validate_task_ready
from app.storage import tasks as task_store
from app.storage.task_dependencies import is_blocked

from .pickup_dispatch import dispatch_to_stage
from .pickup_guards import check_task_dispatchable, validate_autonomous_dispatch
from .pickup_queries import determine_next_stage, get_queued_autonomous_tasks

logger = get_logger(__name__)

# Re-export for callers that import from this module
_determine_next_stage = determine_next_stage


def _dispatch_one(
    task: dict[str, object],
    project_id: str,
    dispatch: Callable[[str, str, str], None] | None,
    dispatched: dict[str, int],
) -> None:
    """Dispatch a single task and update counters in place."""
    task_id = str(task["id"])

    if is_blocked(task_id):
        logger.info("Task blocked by dependency, skipping", task_id=task_id)
        dispatched["skipped"] += 1
        return

    stage = _determine_next_stage(task_id)
    if stage == "execution":
        readiness = validate_task_ready(task_id, project_id)
        if not readiness.ready:
            logger.info("Task not execution-ready, skipping", task_id=task_id, issues=readiness.issues[:3])
            dispatched["skipped"] += 1
            return

    try:
        if dispatch_to_stage(stage, task_id, project_id, dispatch):
            dispatched[stage] = dispatched.get(stage, 0) + 1
        else:
            dispatched["skipped"] += 1
    except Exception as e:
        logger.warning("Failed to dispatch task", task_id=task_id, error=str(e))
        dispatched["skipped"] += 1


def autonomous_work_pickup(
    project_id: str,
    dispatch: Callable[[str, str, str], None] | None = None,
) -> dict[str, object]:
    """Pick up queued autonomous tasks and dispatch to appropriate pipeline stage.

    Args:
        project_id: Project ID to process
        dispatch: Optional dispatch callback function

    Returns:
        Dict with dispatch counts
    """
    logger.info("Starting autonomous work pickup", project_id=project_id)

    if error := validate_autonomous_dispatch(project_id):
        return error

    tasks = get_queued_autonomous_tasks(project_id)
    if not tasks:
        return {"project_id": project_id, "dispatched": 0, "message": "No tasks in queue"}

    dispatched: dict[str, int] = {"triage": 0, "planning": 0, "execution": 0, "skipped": 0}

    for task in tasks:
        _dispatch_one(task, project_id, dispatch, dispatched)

    total = sum(dispatched.values())
    logger.info("Work pickup complete", project_id=project_id, dispatched=dispatched)

    return {"project_id": project_id, "dispatched": total, "breakdown": dispatched}


def dispatch_task_immediate(
    task_id: str,
    project_id: str,
    dispatch: Callable[[str, str, str], None] | None = None,
) -> dict[str, object]:
    """Dispatch a single task immediately (event-driven path from st autocode)."""
    logger.info("Immediate dispatch requested", task_id=task_id, project_id=project_id)

    task = task_store.get_task(task_id)
    if not task:
        logger.warning("Task not found for dispatch", task_id=task_id)
        return {"status": "error", "task_id": task_id, "reason": "task_not_found"}

    if dispatchable_error := check_task_dispatchable(task):
        logger.info(
            "Task not dispatchable",
            task_id=task_id,
            status=task.get("status"),
        )
        return dispatchable_error

    if error := validate_autonomous_dispatch(project_id):
        return {**error, "task_id": task_id}

    if is_blocked(task_id):
        logger.info("Task blocked by dependency", task_id=task_id)
        return {"status": "failed", "task_id": task_id, "reason": "dependency_blocked"}

    stage = _determine_next_stage(task_id)
    if stage == "execution":
        readiness = validate_task_ready(task_id, project_id)
        if not readiness.ready:
            logger.info("Task not execution-ready for immediate dispatch", task_id=task_id, issues=readiness.issues[:3])
            return {"status": "not_ready", "task_id": task_id, "issues": readiness.issues, "suggestions": readiness.suggestions}

    try:
        if dispatch_to_stage(stage, task_id, project_id, dispatch, worker_id_prefix="dispatch"):
            logger.info("Dispatched to %s (immediate)", stage, task_id=task_id)
            return {"status": "dispatched", "task_id": task_id, "stage": stage}

        return {"status": "already_claimed", "task_id": task_id}

    except Exception as e:
        logger.error("Failed to dispatch task", task_id=task_id, error=str(e))
        return {"status": "error", "task_id": task_id, "error": str(e)}
