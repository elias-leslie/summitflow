"""Storage helpers: apply enrichment results to the database."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from ...constants import CLAUDE_OPUS_FULL
from .models import EnrichedTask

logger = logging.getLogger(__name__)
ENRICHMENT_STATUS_REVIEW = "review"


def _update_task_with_enrichment(
    task_id: str,
    enriched: EnrichedTask,
) -> dict[str, Any] | None:
    from ...storage.tasks import update_task

    return update_task(
        task_id,
        title=enriched.title,
        objective=enriched.objective,
        description=enriched.description,
        task_type=enriched.task_type,
        priority=enriched.priority,
        labels=enriched.labels,
        enrichment_status=ENRICHMENT_STATUS_REVIEW,
        enriched_by=CLAUDE_OPUS_FULL,
        enriched_at=datetime.now(UTC),
    )


def _serialize_subtasks(enriched: EnrichedTask) -> list[dict[str, Any]]:
    return [
        {
            "subtask_id": subtask.subtask_id,
            "phase": subtask.phase,
            "description": subtask.description,
            "steps": subtask.steps,
        }
        for subtask in enriched.subtasks
    ]


def _count_steps(enriched: EnrichedTask) -> int:
    return sum(len(subtask.steps) for subtask in enriched.subtasks)


def apply_enrichment_to_task(
    task_id: str,
    enriched: EnrichedTask,
) -> dict[str, Any]:
    """Apply enrichment results to a task in the database."""
    from ...storage.subtasks import bulk_create_subtasks, delete_subtasks_for_task

    updated = _update_task_with_enrichment(task_id, enriched)
    if updated is None:
        raise ValueError(f"Task {task_id} not found")

    delete_subtasks_for_task(task_id)
    subtask_dicts = _serialize_subtasks(enriched)
    bulk_create_subtasks(task_id, subtask_dicts)

    logger.info(
        "Applied enrichment to task %s: %d subtasks, %d steps created",
        task_id,
        len(subtask_dicts),
        _count_steps(enriched),
    )
    return updated
