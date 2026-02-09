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
from datetime import datetime
from typing import Any

from app.logging_config import get_logger
from app.storage import agent_configs
from app.storage import tasks as task_store
from app.storage.connection import get_connection
from app.storage.subtasks import get_subtasks_for_task
from app.storage.task_spirit import get_task_spirit
from app.storage.tasks.claims import claim_task

logger = get_logger(__name__)


def _get_queued_autonomous_tasks(project_id: str, limit: int = 10) -> list[dict[str, Any]]:
    """Get autonomous tasks in queue status ready for pickup.

    Args:
        project_id: Project ID to filter by
        limit: Max tasks to return

    Returns:
        List of task dicts
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, title, task_type, complexity, status
            FROM tasks
            WHERE project_id = %s
              AND status = 'queue'
              AND autonomous = TRUE
              AND (claimed_by IS NULL OR lock_expires_at < NOW())
            ORDER BY priority ASC, created_at ASC
            LIMIT %s
            """,
            (project_id, limit),
        )
        rows = cur.fetchall()

    return [
        {
            "id": row[0],
            "title": row[1],
            "task_type": row[2],
            "complexity": row[3],
            "status": row[4],
        }
        for row in rows
    ]


def _get_tasks_awaiting_review(project_id: str, limit: int = 10) -> list[dict[str, Any]]:
    """Get autonomous tasks waiting for AI review.

    Args:
        project_id: Project ID to filter by
        limit: Max tasks to return

    Returns:
        List of task dicts
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, title, complexity, status
            FROM tasks
            WHERE project_id = %s
              AND status = 'pr_created'
              AND autonomous = TRUE
            ORDER BY created_at ASC
            LIMIT %s
            """,
            (project_id, limit),
        )
        rows = cur.fetchall()

    return [
        {
            "id": row[0],
            "title": row[1],
            "complexity": row[2],
            "status": row[3],
        }
        for row in rows
    ]


def _determine_next_stage(task_id: str) -> str:
    """Determine which pipeline stage a queued task needs.

    Returns:
        Stage name: 'triage', 'planning', 'execution', or 'unknown'
    """
    spirit = get_task_spirit(task_id)
    subtasks = get_subtasks_for_task(task_id)

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

    This task runs periodically to:
    1. Check if within autonomous hours
    2. Find tasks in 'queue' status with autonomous=True
    3. Determine which stage each needs (triage, planning, execution)
    4. Dispatch to the appropriate workflow

    Args:
        project_id: Project ID to process

    Returns:
        Dict with dispatch counts
    """
    logger.info("Starting autonomous work pickup", project_id=project_id)

    # Check if autonomous is enabled
    if not agent_configs.is_autonomous_enabled(project_id):
        return {
            "status": "disabled",
            "reason": "autonomous_enabled=false",
        }

    # Check if within autonomous time window
    current_hour = datetime.now().hour
    if not agent_configs.is_within_autonomous_hours(project_id, current_hour):
        schedule = agent_configs.get_autonomous_schedule(project_id)
        return {
            "status": "outside_hours",
            "current_hour": current_hour,
            "start_hour": schedule.get("start_hour", 0),
            "end_hour": schedule.get("end_hour", 24),
        }

    # Check concurrency limit
    schedule = agent_configs.get_autonomous_schedule(project_id)
    max_concurrent = schedule.get("max_concurrent", 1)
    running_count = task_store.count_running_tasks(project_id)
    if running_count >= max_concurrent:
        return {
            "status": "concurrency_limit",
            "running_count": running_count,
            "max_concurrent": max_concurrent,
        }

    tasks = _get_queued_autonomous_tasks(project_id)
    if not tasks:
        return {"project_id": project_id, "dispatched": 0, "message": "No tasks in queue"}

    dispatched = {"triage": 0, "planning": 0, "execution": 0, "skipped": 0}

    for task in tasks:
        task_id = task["id"]
        stage = _determine_next_stage(task_id)

        try:
            if stage == "triage":
                if dispatch:
                    dispatch("triage", task_id, project_id)
                dispatched["triage"] += 1
                logger.info("Dispatched to triage", task_id=task_id)

            elif stage == "planning":
                if dispatch:
                    dispatch("plan", task_id, project_id)
                dispatched["planning"] += 1
                logger.info("Dispatched to planning", task_id=task_id)

            elif stage == "execution":
                # Atomically claim task to prevent duplicate dispatch
                worker_id = f"pickup-{project_id}"
                claimed = claim_task(task_id, worker_id, lock_duration_minutes=60)
                if not claimed:
                    logger.info(
                        "Task already claimed, skipping",
                        task_id=task_id,
                    )
                    dispatched["skipped"] += 1
                    continue

                if dispatch:
                    dispatch("execute", task_id, project_id)
                dispatched["execution"] += 1
                logger.info("Dispatched to execution", task_id=task_id)

            else:
                dispatched["skipped"] += 1
                logger.warning("Unknown stage, skipping", task_id=task_id, stage=stage)

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

    This task runs periodically to:
    1. Find tasks in 'pr_created' status with autonomous=True
    2. Dispatch to AI review

    Args:
        project_id: Project ID to process

    Returns:
        Dict with review dispatch count
    """
    logger.info("Starting review task pickup", project_id=project_id)

    tasks = _get_tasks_awaiting_review(project_id)
    if not tasks:
        return {"project_id": project_id, "dispatched": 0, "message": "No tasks awaiting review"}

    dispatched = 0
    for task in tasks:
        task_id = task["id"]
        try:
            if dispatch:
                dispatch("review", task_id, project_id)
            dispatched += 1
            logger.info("Dispatched to AI review", task_id=task_id)
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

    Returns:
        Dict with dispatch result
    """
    logger.info("Immediate dispatch requested", task_id=task_id, project_id=project_id)

    # Guard: check task status before any dispatch
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

    if not agent_configs.is_autonomous_enabled(project_id):
        return {
            "status": "disabled",
            "task_id": task_id,
            "reason": "autonomous_enabled=false",
        }

    current_hour = datetime.now().hour
    if not agent_configs.is_within_autonomous_hours(project_id, current_hour):
        schedule = agent_configs.get_autonomous_schedule(project_id)
        return {
            "status": "outside_hours",
            "task_id": task_id,
            "current_hour": current_hour,
            "start_hour": schedule.get("start_hour", 0),
            "end_hour": schedule.get("end_hour", 24),
        }

    schedule = agent_configs.get_autonomous_schedule(project_id)
    max_concurrent = schedule.get("max_concurrent", 1)
    running_count = task_store.count_running_tasks(project_id)
    if running_count >= max_concurrent:
        return {
            "status": "concurrency_limit",
            "task_id": task_id,
            "running_count": running_count,
            "max_concurrent": max_concurrent,
        }

    stage = _determine_next_stage(task_id)

    try:
        if stage == "triage":
            if dispatch:
                dispatch("triage", task_id, project_id)
            logger.info("Dispatched to triage (immediate)", task_id=task_id)
            return {"status": "dispatched", "task_id": task_id, "stage": "triage"}

        elif stage == "planning":
            if dispatch:
                dispatch("plan", task_id, project_id)
            logger.info("Dispatched to planning (immediate)", task_id=task_id)
            return {"status": "dispatched", "task_id": task_id, "stage": "planning"}

        elif stage == "execution":
            # Atomically claim task to prevent duplicate execution
            worker_id = f"dispatch-{project_id}"
            claimed = claim_task(task_id, worker_id, lock_duration_minutes=60)
            if not claimed:
                logger.info(
                    "Task already claimed, skipping duplicate execution dispatch",
                    task_id=task_id,
                )
                return {"status": "already_claimed", "task_id": task_id}

            if dispatch:
                dispatch("execute", task_id, project_id)
            logger.info("Dispatched to execution (immediate)", task_id=task_id)
            return {"status": "dispatched", "task_id": task_id, "stage": "execution"}

        else:
            logger.warning("Unknown stage for immediate dispatch", task_id=task_id, stage=stage)
            return {"status": "skipped", "task_id": task_id, "reason": f"unknown stage: {stage}"}

    except Exception as e:
        logger.error("Failed to dispatch task", task_id=task_id, error=str(e))
        return {"status": "error", "task_id": task_id, "error": str(e)}


