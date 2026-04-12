"""Tests for enrichment-service normalization and storage."""

from __future__ import annotations

from unittest.mock import patch

from app.services.enrichment_service._core import _build_enriched_task
from app.services.enrichment_service._storage import apply_enrichment_to_task
from app.services.enrichment_service.models import EnrichedTask, Subtask


def test_build_enriched_task_prefers_done_when_field() -> None:
    enriched = _build_enriched_task(
        {
            "title": "Normalize output",
            "objective": "Use done_when",
            "done_when": ["Tests pass", "Export omits fake fields"],
            "subtasks": [],
        }
    )

    assert enriched.done_when == ["Tests pass", "Export omits fake fields"]


def test_build_enriched_task_accepts_legacy_acceptance_criteria() -> None:
    enriched = _build_enriched_task(
        {
            "title": "Normalize legacy output",
            "objective": "Support old agent output during transition",
            "acceptance_criteria": [
                {"criterion": "Task stores done_when"},
                "Subtasks preserved",
            ],
            "subtasks": [],
        }
    )

    assert enriched.done_when == ["Task stores done_when", "Subtasks preserved"]


def test_apply_enrichment_to_task_upserts_done_when_and_objective() -> None:
    enriched = EnrichedTask(
        title="Enriched title",
        objective="Persist objective in task_spirit context",
        description="Expanded description",
        task_type="task",
        priority=2,
        labels=["tasks"],
        done_when=["Tests pass", "Task export omits synthetic criteria"],
        subtasks=[Subtask(subtask_id="1.1", phase="backend", description="Patch export", steps=["Edit code"])],
        raw_json={},
    )

    with (
        patch("app.services.enrichment_service._storage._update_task_with_enrichment", return_value={"id": "task-1"}),
        patch("app.storage.subtasks.delete_subtasks_for_task"),
        patch("app.storage.subtasks.bulk_create_subtasks") as mock_bulk_create,
        patch("app.storage.task_spirit.get_task_spirit", return_value=None),
        patch("app.storage.task_spirit.upsert_task_spirit") as mock_upsert,
    ):
        apply_enrichment_to_task("task-1", enriched)

    mock_upsert.assert_called_once_with(
        task_id="task-1",
        done_when=["Tests pass", "Task export omits synthetic criteria"],
        context={"objective": "Persist objective in task_spirit context"},
    )
    mock_bulk_create.assert_called_once()


def test_apply_enrichment_to_task_merges_existing_context() -> None:
    enriched = EnrichedTask(
        title="Enriched title",
        objective="Refresh objective",
        description="Expanded description",
        task_type="task",
        priority=2,
        labels=[],
        done_when=["Ship verified cleanup"],
        subtasks=[],
        raw_json={},
    )

    with (
        patch("app.services.enrichment_service._storage._update_task_with_enrichment", return_value={"id": "task-2"}),
        patch("app.storage.subtasks.delete_subtasks_for_task"),
        patch("app.storage.subtasks.bulk_create_subtasks"),
        patch(
            "app.storage.task_spirit.get_task_spirit",
            return_value={"context": {"constraints": ["Keep API lean"]}, "done_when": ["Old"]},
        ),
        patch("app.storage.task_spirit.update_task_spirit") as mock_update,
    ):
        apply_enrichment_to_task("task-2", enriched)

    mock_update.assert_called_once_with(
        "task-2",
        done_when=["Ship verified cleanup"],
        context={
            "constraints": ["Keep API lean"],
            "objective": "Refresh objective",
        },
    )
