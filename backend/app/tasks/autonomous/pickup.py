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

from datetime import datetime
from typing import Any

from app.celery_app import celery_app
from app.logging_config import get_logger
from app.scheduling import get_dispatcher
from app.scheduling.dispatch import DispatchEvent
from app.services.worktree import create_task_worktree
from app.storage import agent_configs
from app.storage import tasks as task_store
from app.storage.connection import get_connection
from app.storage.subtasks import get_subtasks_for_task
from app.storage.task_spirit import get_task_spirit

from .execution import start_execution
from .planning import create_plan
from .review import ai_review
from .triage import triage_idea

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


@celery_app.task(
    name="summitflow.autonomous_work_pickup",
    acks_late=True,
    time_limit=600,  # 10 minutes hard limit
    soft_time_limit=540,  # 9 minutes soft limit
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=120,  # Max 2 minutes between retries
    max_retries=3,
)
def autonomous_work_pickup(project_id: str) -> dict[str, Any]:
    """Pick up queued autonomous tasks and dispatch to appropriate pipeline stage.

    This task runs periodically to:
    1. Check if within autonomous hours
    2. Find tasks in 'queue' status with autonomous=True
    3. Determine which stage each needs (triage, planning, execution)
    4. Dispatch to the appropriate Celery task

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
                triage_idea.delay(task_id, project_id)
                dispatched["triage"] += 1
                logger.info("Dispatched to triage", task_id=task_id)

            elif stage == "planning":
                create_plan.delay(task_id, project_id)
                dispatched["planning"] += 1
                logger.info("Dispatched to planning", task_id=task_id)

            elif stage == "execution":
                # Create worktree for task isolation before execution
                worktree = create_task_worktree(task_id, project_id)
                if worktree:
                    logger.info(
                        "Created worktree for execution",
                        task_id=task_id,
                        worktree_path=str(worktree.path),
                        branch=worktree.branch,
                    )
                else:
                    logger.warning(
                        "Worktree creation failed, using project root",
                        task_id=task_id,
                    )

                task_store.update_task_status(task_id, "running")
                start_execution.delay(task_id, project_id)
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


@celery_app.task(
    name="summitflow.review_pending_tasks",
    acks_late=True,
    time_limit=900,  # 15 minutes hard limit
    soft_time_limit=840,  # 14 minutes soft limit
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=180,  # Max 3 minutes between retries
    max_retries=3,
)
def review_pending_tasks(project_id: str) -> dict[str, Any]:
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
            ai_review.delay(task_id, project_id)
            dispatched += 1
            logger.info("Dispatched to AI review", task_id=task_id)
        except Exception as e:
            logger.warning("Failed to dispatch review", task_id=task_id, error=str(e))

    logger.info("Review pickup complete", project_id=project_id, dispatched=dispatched)

    return {"project_id": project_id, "dispatched": dispatched}


@celery_app.task(name="summitflow.dispatch_task_immediate")
def dispatch_task_immediate(task_id: str, project_id: str) -> dict[str, Any]:
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
            triage_idea.delay(task_id, project_id)
            logger.info("Dispatched to triage (immediate)", task_id=task_id)
            return {"status": "dispatched", "task_id": task_id, "stage": "triage"}

        elif stage == "planning":
            create_plan.delay(task_id, project_id)
            logger.info("Dispatched to planning (immediate)", task_id=task_id)
            return {"status": "dispatched", "task_id": task_id, "stage": "planning"}

        elif stage == "execution":
            task_store.update_task_status(task_id, "running")
            start_execution.delay(task_id, project_id)
            logger.info("Dispatched to execution (immediate)", task_id=task_id)
            return {"status": "dispatched", "task_id": task_id, "stage": "execution"}

        else:
            logger.warning("Unknown stage for immediate dispatch", task_id=task_id, stage=stage)
            return {"status": "skipped", "task_id": task_id, "reason": f"unknown stage: {stage}"}

    except Exception as e:
        logger.error("Failed to dispatch task", task_id=task_id, error=str(e))
        return {"status": "error", "task_id": task_id, "error": str(e)}


@celery_app.task(name="summitflow.process_scheduled_tasks")
def process_scheduled_tasks() -> dict[str, Any]:
    """Process scheduled tasks that are due for execution.

    Checks Redis sorted set for tasks with schedule <= now.
    Called periodically by Celery Beat (every 1 minute).

    Returns:
        Dict with processing results
    """
    dispatcher = get_dispatcher()
    due_events = dispatcher.get_due_scheduled_tasks()

    if not due_events:
        return {"processed": 0}

    processed = 0
    for event in due_events:
        try:
            dispatch_task_immediate.delay(event.task_id, event.project_id)
            processed += 1
            logger.info(
                "Dispatched scheduled task",
                task_id=event.task_id,
                queued_at=event.queued_at.isoformat(),
            )
        except Exception as e:
            logger.warning(
                "Failed to dispatch scheduled task",
                task_id=event.task_id,
                error=str(e),
            )

    return {"processed": processed}


def handle_dispatch_event(event: DispatchEvent) -> None:
    """Handle a dispatch event from Redis pub/sub.

    Called by the subscriber when a task is queued via st autocode.
    """
    if event.schedule is None:
        dispatch_task_immediate.delay(event.task_id, event.project_id)
    else:
        logger.debug(
            "Scheduled task stored, will be processed by Beat",
            task_id=event.task_id,
            schedule=event.schedule.to_dict(),
        )
