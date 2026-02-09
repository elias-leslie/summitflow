"""Background task for processing crowdsourced ideas."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from app.storage.connection import get_connection

logger = logging.getLogger(__name__)

DEFAULT_AUTOMATION_SETTINGS = {
    "schedule_preset": "nightly",
    "cron_expression": "0 3 * * *",
    "daily_budget_usd": 5.0,
    "primary_agent": "gemini",
    "secondary_agent": "claude",
    "enabled": False,
}


def get_project_automation_settings(project_id: str) -> dict[str, Any]:
    """Get automation settings for a project."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT automation_settings FROM projects WHERE id = %s",
            (project_id,),
        )
        row = cur.fetchone()
        if not row or not row[0]:
            return dict(DEFAULT_AUTOMATION_SETTINGS)
        return dict(row[0])


def get_approved_ideas_by_priority(project_id: str, limit: int = 10) -> list[dict[str, Any]]:
    """Get approved ideas sorted by priority score (ROI)."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, refined_text, category, complexity, priority_score, task_id
            FROM ideas
            WHERE project_id = %s
              AND status = 'approved'
              AND task_id IS NOT NULL
            ORDER BY priority_score DESC NULLS LAST
            LIMIT %s
            """,
            (project_id, limit),
        )
        rows = cur.fetchall()
        return [
            {
                "id": row[0],
                "refined_text": row[1],
                "category": row[2],
                "complexity": row[3],
                "priority_score": row[4],
                "task_id": row[5],
            }
            for row in rows
        ]


def update_idea_status(idea_id: str, status: str) -> None:
    """Update idea status and create notification if completed."""
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE ideas SET status = %s, updated_at = %s WHERE id = %s",
            (status, now, idea_id),
        )
        if status == "completed":
            cur.execute(
                "UPDATE ideas SET completed_at = %s WHERE id = %s",
                (now, idea_id),
            )

            # Create notification for the idea submitter
            cur.execute(
                """
                SELECT project_id, user_email, refined_text, task_id
                FROM ideas WHERE id = %s
                """,
                (idea_id,),
            )
            idea_row = cur.fetchone()
            if idea_row and idea_row[1]:  # Has user_email
                from app.storage.notifications import create_idea_completion_notification

                project_id = idea_row[0]
                user_email = idea_row[1]
                idea_title = (idea_row[2] or "")[:50]  # First 50 chars
                task_id = idea_row[3]

                try:
                    create_idea_completion_notification(
                        project_id=project_id,
                        user_email=user_email,
                        idea_id=idea_id,
                        idea_title=idea_title,
                        task_id=task_id,
                    )
                    logger.info(
                        f"Created completion notification for idea {idea_id} to {user_email}"
                    )
                except Exception as e:
                    logger.warning(f"Failed to create notification for idea {idea_id}: {e}")

        conn.commit()


def process_crowdsourced_ideas(
    project_id: str,
    dispatch: Callable[[str, str, str], None] | None = None,
) -> dict[str, Any]:
    """Process approved crowdsourced ideas for a project.

    Executes ideas sequentially up to the daily budget limit.
    Uses the project's automation settings for agent selection.

    Args:
        project_id: Project to process ideas for

    Returns:
        Dict with execution results
    """
    from app.storage import tasks as task_store

    # Load automation settings
    settings = get_project_automation_settings(project_id)

    # Check if enabled
    if not settings.get("enabled", False):
        logger.debug(f"Crowdsourced idea automation disabled for {project_id}")
        return {"status": "disabled", "project_id": project_id}

    budget_limit = settings.get("daily_budget_usd", 5.0)
    cumulative_cost = 0.0
    processed = []
    skipped = []

    # Get approved ideas by priority
    ideas = get_approved_ideas_by_priority(project_id)

    if not ideas:
        logger.info(f"No approved ideas to process for {project_id}")
        return {
            "status": "no_ideas",
            "project_id": project_id,
            "processed": 0,
        }

    for idea in ideas:
        idea_id = idea["id"]
        task_id = idea["task_id"]

        # Check budget
        if cumulative_cost >= budget_limit:
            skipped.append({"idea_id": idea_id, "reason": "budget_exceeded"})
            logger.info(f"Budget exceeded, skipping idea {idea_id}")
            continue

        # Get linked task
        task = task_store.get_task(task_id)
        if not task:
            skipped.append({"idea_id": idea_id, "reason": "task_not_found"})
            continue

        if task.get("status") not in ("pending", "paused"):
            skipped.append({"idea_id": idea_id, "reason": f"task_status_{task.get('status')}"})
            continue

        try:
            # Update idea to executing
            update_idea_status(idea_id, "executing")

            # Dispatch execution via autonomous work pickup
            # This triggers the existing implementation pipeline
            logger.info(f"Dispatching idea {idea_id} via task {task_id}")

            if dispatch:
                dispatch("execute", task_id, project_id)

            # Estimate cost (placeholder - real cost tracking would come from Agent Hub)
            estimated_cost = 0.50  # Conservative estimate per task
            cumulative_cost += estimated_cost

            processed.append(
                {
                    "idea_id": idea_id,
                    "task_id": task_id,
                    "cost": estimated_cost,
                }
            )

        except Exception as e:
            logger.error(f"Failed to dispatch idea {idea_id}: {e}")
            update_idea_status(idea_id, "failed")
            skipped.append({"idea_id": idea_id, "reason": str(e)})

    return {
        "status": "completed",
        "project_id": project_id,
        "processed": len(processed),
        "skipped": len(skipped),
        "total_cost": cumulative_cost,
        "budget_remaining": budget_limit - cumulative_cost,
        "details": {
            "processed": processed,
            "skipped": skipped,
        },
    }
