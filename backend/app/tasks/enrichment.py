"""Background tasks for AI-powered task enrichment.

These tasks run in the background to enrich tasks with AI-generated
objectives, acceptance criteria, and implementation subtasks.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _mark_enrichment_failed(task_id: str, error: Exception) -> None:
    """Mark a task as failed in the database after enrichment error."""
    from ..storage.tasks import update_task

    try:
        update_task(
            task_id,
            enrichment_status="failed",
            error_message=str(error),
        )
    except Exception as update_err:
        logger.error("Failed to update task status: %s", update_err)


def _build_enrichment_result(task_id: str, enriched: Any, validation: Any) -> dict[str, Any]:
    """Build the result dict from a successful enrichment."""
    return {
        "task_id": task_id,
        "status": "review",
        "criteria_count": len(enriched.acceptance_criteria),
        "subtask_count": len(enriched.subtasks),
        "valid": validation.valid,
    }


def enrich_task_async(
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

    logger.info("Starting async enrichment for task %s", task_id)

    try:
        enriched, validation = enrich_and_validate(
            project_id=project_id,
            task_id=task_id,
            raw_request=raw_request,
        )
        apply_enrichment_to_task(task_id, enriched)

        logger.info(
            "Enrichment complete for task %s: %d criteria, %d subtasks, valid=%s",
            task_id,
            len(enriched.acceptance_criteria),
            len(enriched.subtasks),
            validation.valid,
        )

        return _build_enrichment_result(task_id, enriched, validation)

    except Exception as e:
        logger.error("Enrichment failed for task %s: %s", task_id, e)
        _mark_enrichment_failed(task_id, e)
        raise  # Re-raise to trigger retry
