"""Storage helpers: apply enrichment results to the database."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ...logging_config import get_logger
from ...services.task_plan_context import build_task_plan_context
from .models import EnrichedTask

logger = get_logger(__name__)
ENRICHMENT_STATUS_REVIEW = "review"
ENRICHMENT_AGENT = "agent:planner"


def _update_task_with_enrichment(
    task_id: str,
    enriched: EnrichedTask,
) -> dict[str, Any] | None:
    from ...storage.tasks import update_task

    return update_task(
        task_id,
        title=enriched.title,
        description=enriched.description,
        task_type=enriched.task_type,
        priority=enriched.priority,
        labels=enriched.labels,
        enrichment_status=ENRICHMENT_STATUS_REVIEW,
        enriched_by=ENRICHMENT_AGENT,
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


def _persist_spirit_fields(task_id: str, enriched: EnrichedTask) -> None:
    from ...storage.task_spirit import get_task_spirit, update_task_spirit, upsert_task_spirit

    existing = get_task_spirit(task_id)
    existing_context = existing.get("context") if isinstance(existing, dict) else None
    merged_context: dict[str, Any] = (
        dict(existing_context) if isinstance(existing_context, dict) else {}
    )
    merged_context.update(build_task_plan_context({"objective": enriched.objective}))

    payload: dict[str, Any] = {}
    if enriched.done_when:
        payload["done_when"] = enriched.done_when
    if merged_context:
        payload["context"] = merged_context
    if not payload:
        return

    if existing:
        update_task_spirit(task_id, **payload)
        return
    upsert_task_spirit(task_id=task_id, **payload)


def apply_enrichment_to_task(
    task_id: str,
    enriched: EnrichedTask,
) -> dict[str, Any]:
    """Apply enrichment results to a task in the database."""
    from ...storage.subtasks import bulk_create_subtasks, delete_subtasks_for_task

    updated = _update_task_with_enrichment(task_id, enriched)
    if updated is None:
        raise ValueError(f"Task {task_id} not found")

    _persist_spirit_fields(task_id, enriched)
    delete_subtasks_for_task(task_id)
    subtask_dicts = _serialize_subtasks(enriched)
    bulk_create_subtasks(task_id, subtask_dicts)

    logger.info(
        "Applied enrichment to task %s: %d done_when items, %d subtasks, %d steps created",
        task_id,
        len(enriched.done_when),
        len(subtask_dicts),
        _count_steps(enriched),
    )
    return updated
