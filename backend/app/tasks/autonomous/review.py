"""Celery task for Opus review of pending tasks."""

from __future__ import annotations

import logging
from typing import Any

from app.celery_app import celery_app
from app.storage import tasks as task_store

logger = logging.getLogger(__name__)


@celery_app.task(name="summitflow.review_pending_tasks")  # type: ignore[untyped-decorator]
def review_pending_tasks(project_id: str) -> dict[str, Any]:
    """Review tasks in ai_reviewing status via Opus.

    Fetches tasks awaiting review and runs Opus review on each.
    Applies the appropriate handler based on verdict.

    Args:
        project_id: Project to review tasks for

    Returns:
        Dict with reviewed_count, verdicts breakdown, and any errors
    """
    from app.services.autonomous.reviewer import (
        handle_approval,
        handle_fix_request,
        handle_rejection,
        opus_review,
    )
    from app.storage.agent_configs import is_autonomous_enabled

    try:
        # Check if autonomous execution is enabled
        if not is_autonomous_enabled(project_id):
            logger.debug(f"Autonomous execution disabled for {project_id}")
            return {"status": "disabled", "reason": "autonomous_enabled=false"}

        # Get tasks in ai_reviewing status
        pending_tasks = task_store.list_tasks(
            project_id=project_id,
            status_filter="ai_reviewing",
            limit=5,  # Review up to 5 at a time
        )

        if not pending_tasks:
            return {"status": "no_tasks", "reviewed_count": 0}

        verdicts: dict[str, int] = {"APPROVE": 0, "REJECT": 0, "REQUEST_FIX": 0}
        reviewed = 0
        errors: list[dict[str, str]] = []

        for task in pending_tasks:
            task_id = task["id"]
            try:
                # Run Opus review
                review_result = opus_review(task)
                verdict = review_result.get("verdict", "REQUEST_FIX")
                verdicts[verdict] = verdicts.get(verdict, 0) + 1
                reviewed += 1

                # Apply appropriate handler
                if verdict == "APPROVE":
                    handle_approval(task, review_result, auto_push=False)
                    logger.info(f"Task {task_id} approved by Opus review")
                elif verdict == "REJECT":
                    handle_rejection(task, review_result)
                    logger.info(f"Task {task_id} rejected by Opus review")
                else:  # REQUEST_FIX
                    handle_fix_request(task, review_result)
                    logger.info(f"Task {task_id} needs fixes per Opus review")

            except Exception as task_error:
                logger.error(f"Error reviewing task {task_id}: {task_error}")
                errors.append({"task_id": task_id, "error": str(task_error)})

        logger.info(
            f"Review complete for {project_id}: reviewed={reviewed}, "
            f"approved={verdicts['APPROVE']}, rejected={verdicts['REJECT']}, "
            f"fix_requested={verdicts['REQUEST_FIX']}"
        )

        return {
            "status": "success",
            "reviewed_count": reviewed,
            "verdicts": verdicts,
            "errors": errors if errors else None,
        }

    except Exception as e:
        logger.error(f"Error in review_pending_tasks: {e}")
        return {"status": "error", "error": str(e)}
