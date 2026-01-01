"""Celery tasks for AI-powered task enrichment.

These tasks run in the background to enrich tasks with AI-generated
objectives, acceptance criteria, and implementation subtasks.
"""

from __future__ import annotations

import logging
from typing import Any

from celery import shared_task  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)


@shared_task(  # type: ignore[untyped-decorator]
    name="enrich_task_async",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 2},
)
def enrich_task_async(
    self: Any,
    project_id: str,
    task_id: str,
    raw_request: str,
) -> dict[str, Any]:
    """Enrich a task with AI-generated structure.

    This task:
    1. Gathers project context
    2. Calls Opus to generate objective, criteria, subtasks
    3. Validates with Gemini
    4. Stores results in the database

    Args:
        project_id: Project ID
        task_id: Task ID to enrich
        raw_request: User's raw request text

    Returns:
        Dict with task_id and status
    """
    from ..services.enrichment_service import (
        apply_enrichment_to_task,
        enrich_and_validate,
    )
    from ..storage.tasks import update_task

    logger.info("Starting async enrichment for task %s", task_id)

    try:
        # Run enrichment
        enriched, validation = enrich_and_validate(
            project_id=project_id,
            task_id=task_id,
            raw_request=raw_request,
        )

        # Apply to database
        apply_enrichment_to_task(task_id, enriched)

        logger.info(
            "Enrichment complete for task %s: %d criteria, %d subtasks, valid=%s",
            task_id,
            len(enriched.acceptance_criteria),
            len(enriched.subtasks),
            validation.valid,
        )

        return {
            "task_id": task_id,
            "status": "review",
            "criteria_count": len(enriched.acceptance_criteria),
            "subtask_count": len(enriched.subtasks),
            "valid": validation.valid,
        }

    except Exception as e:
        logger.error("Enrichment failed for task %s: %s", task_id, e)

        # Mark task as failed
        try:
            update_task(
                task_id,
                enrichment_status="failed",
                error_message=str(e),
            )
        except Exception as update_err:
            logger.error("Failed to update task status: %s", update_err)

        raise  # Re-raise to trigger retry
