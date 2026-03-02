"""Storage helpers: apply enrichment results to the database."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from ...constants import CLAUDE_OPUS_FULL
from .models import EnrichedTask

logger = logging.getLogger(__name__)


def apply_enrichment_to_task(
    task_id: str,
    enriched: EnrichedTask,
) -> dict[str, Any]:
    """Apply enrichment results to a task in the database.

    Args:
        task_id: Task ID to update
        enriched: Enriched task data

    Returns:
        Updated task dict
    """
    from ...storage.subtasks import bulk_create_subtasks, delete_subtasks_for_task
    from ...storage.tasks import update_task

    updated = update_task(
        task_id,
        title=enriched.title,
        objective=enriched.objective,
        description=enriched.description,
        task_type=enriched.task_type,
        priority=enriched.priority,
        labels=enriched.labels,
        enrichment_status="review",
        enriched_by=CLAUDE_OPUS_FULL,
        enriched_at=datetime.now(UTC),
    )

    if updated is None:
        raise ValueError(f"Task {task_id} not found")

    delete_subtasks_for_task(task_id)
    subtask_dicts = [
        {
            "subtask_id": s.subtask_id,
            "phase": s.phase,
            "description": s.description,
            "steps": s.steps,
        }
        for s in enriched.subtasks
    ]
    bulk_create_subtasks(task_id, subtask_dicts)

    total_steps = sum(len(s.steps) for s in enriched.subtasks)
    logger.info(
        "Applied enrichment to task %s: %d subtasks, %d steps created",
        task_id,
        len(subtask_dicts),
        total_steps,
    )

    return updated
