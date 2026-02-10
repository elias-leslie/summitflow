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
from typing import Any

from app.logging_config import get_logger
from app.storage import tasks as task_store
from app.storage.subtasks import get_subtasks_for_task
from app.storage.task_dependencies import is_blocked
from app.storage.task_spirit import get_task_spirit

from .pickup_dispatch import dispatch_to_review, dispatch_to_stage
from .pickup_guards import validate_autonomous_dispatch
from .pickup_queries import get_queued_autonomous_tasks, get_tasks_awaiting_review

logger = get_logger(__name__)


def _determine_next_stage(task_id: str) -> str:
    """Determine which pipeline stage a queued task needs.

    Returns:
        Stage name: 'ideation', 'triage', 'planning', 'execution', or 'unknown'
    """
    task = task_store.get_task(task_id)
    spirit = get_task_spirit(task_id)
    subtasks = get_subtasks_for_task(task_id)

    # Crowdsourced ideas without an objective need ideation first
    is_crowdsourced = task and "crowdsourced" in (task.get("labels") or [])
    if is_crowdsourced and (not spirit or not spirit.get("objective")):
        return "ideation"

    if not spirit or not spirit.get("objective"):
        return "triage"

    if not subtasks:
        return "planning"

    incomplete = [s for s in subtasks if not s.get("passes")]
    if incomplete:
        return "execution"

    return "unknown"


def autonomous_work_pickup(
    project_id: str,
    dispatch: Callable[[str, str, str], None] | None = None,
) -> dict[str, Any]:
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

    dispatched = {"triage": 0, "planning": 0, "execution": 0, "skipped": 0}

    for task in tasks:
        task_id = task["id"]

        # Skip tasks with unresolved dependencies
        if is_blocked(task_id):
            logger.info("Task blocked by dependency, skipping", task_id=task_id)
            dispatched["skipped"] += 1
            continue

        stage = _determine_next_stage(task_id)

        try:
            if dispatch_to_stage(stage, task_id, project_id, dispatch):
                dispatched[stage] += 1
            else:
                dispatched["skipped"] += 1
        except Exception as e:
            logger.warning("Failed to dispatch task", task_id=task_id, error=str(e))
            dispatched["skipped"] += 1

    total = sum(dispatched.values())
    logger.info("Work pickup complete", project_id=project_id, dispatched=dispatched)

    return {"project_id": project_id, "dispatched": total, "breakdown": dispatched}


def review_pending_tasks(
    project_id: str,
    dispatch: Callable[[str, str, str], None] | None = None,
) -> dict[str, Any]:
    """Pick up tasks awaiting AI review and dispatch to reviewer.

    Args:
        project_id: Project ID to process
        dispatch: Optional dispatch callback function

    Returns:
        Dict with review dispatch count
    """
    logger.info("Starting review task pickup", project_id=project_id)

    tasks = get_tasks_awaiting_review(project_id)
    if not tasks:
        return {"project_id": project_id, "dispatched": 0, "message": "No tasks awaiting review"}

    dispatched = 0
    for task in tasks:
        task_id = task["id"]
        try:
            if dispatch_to_review(task_id, project_id, dispatch):
                dispatched += 1
        except Exception as e:
            logger.warning("Failed to dispatch review", task_id=task_id, error=str(e))

    logger.info("Review pickup complete", project_id=project_id, dispatched=dispatched)

    return {"project_id": project_id, "dispatched": dispatched}


def dispatch_task_immediate(
    task_id: str,
    project_id: str,
    dispatch: Callable[[str, str, str], None] | None = None,
) -> dict[str, Any]:
    """Dispatch a single task immediately (event-driven path).

    Called when st autocode publishes to Redis pub/sub.
    Bypasses polling delay for instant task pickup.

    Args:
        task_id: Task to dispatch
        project_id: Project ID
        dispatch: Optional dispatch callback function

    Returns:
        Dict with dispatch result
    """
    logger.info("Immediate dispatch requested", task_id=task_id, project_id=project_id)

    task = task_store.get_task(task_id)
    if not task:
        logger.warning("Task not found for dispatch", task_id=task_id)
        return {"status": "error", "task_id": task_id, "reason": "task_not_found"}

    if task["status"] == "running":
        logger.info(
            "Task already running, skipping duplicate dispatch",
            task_id=task_id,
            claimed_by=task.get("claimed_by"),
        )
        return {"status": "already_running", "task_id": task_id}

    if task["status"] not in ("queue", "pending", "blocked"):
        logger.info(
            "Task not in dispatchable status",
            task_id=task_id,
            status=task["status"],
        )
        return {"status": "skipped", "task_id": task_id, "reason": f"status={task['status']}"}

    if error := validate_autonomous_dispatch(project_id):
        return {**error, "task_id": task_id}

    if is_blocked(task_id):
        logger.info("Task blocked by dependency", task_id=task_id)
        return {"status": "blocked", "task_id": task_id, "reason": "dependency_blocked"}

    stage = _determine_next_stage(task_id)

    try:
        if dispatch_to_stage(stage, task_id, project_id, dispatch, worker_id_prefix="dispatch"):
            logger.info(f"Dispatched to {stage} (immediate)", task_id=task_id)
            return {"status": "dispatched", "task_id": task_id, "stage": stage}

        return {"status": "already_claimed", "task_id": task_id}

    except Exception as e:
        logger.error("Failed to dispatch task", task_id=task_id, error=str(e))
        return {"status": "error", "task_id": task_id, "error": str(e)}
