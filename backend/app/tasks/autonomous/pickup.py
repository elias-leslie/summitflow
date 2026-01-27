"""Autonomous work pickup and review tasks.

Scheduled Celery tasks that poll for eligible tasks and dispatch them
through the autonomous execution pipeline.
"""

from __future__ import annotations

from typing import Any

from app.celery_app import celery_app
from app.logging_config import get_logger
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


@celery_app.task(name="summitflow.autonomous_work_pickup")
def autonomous_work_pickup(project_id: str) -> dict[str, Any]:
    """Pick up queued autonomous tasks and dispatch to appropriate pipeline stage.

    This task runs periodically to:
    1. Find tasks in 'queue' status with autonomous=True
    2. Determine which stage each needs (triage, planning, execution)
    3. Dispatch to the appropriate Celery task

    Args:
        project_id: Project ID to process

    Returns:
        Dict with dispatch counts
    """
    logger.info("Starting autonomous work pickup", project_id=project_id)

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


@celery_app.task(name="summitflow.review_pending_tasks")
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
