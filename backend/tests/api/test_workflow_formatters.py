"""Tests for task workflow TOON formatters."""

from __future__ import annotations

from app.api.tasks.workflow_formatters import format_toon_context

FRESHNESS_LINE = (
    "FRESHNESS:verify-system-project-state|"
    "task-text=historical|"
    "reshape-or-abandon-if-stale"
)


def test_format_toon_context_includes_task_freshness_for_active_tasks() -> None:
    task = {
        "id": "task-fresh",
        "project_id": "summitflow",
        "status": "pending",
        "priority": 2,
        "task_type": "task",
        "complexity": "STANDARD",
        "title": "Review stale task safely",
    }

    output = format_toon_context(task, None, [], [])

    assert FRESHNESS_LINE in output


def test_format_toon_context_omits_task_freshness_for_final_tasks() -> None:
    task = {
        "id": "task-done",
        "project_id": "summitflow",
        "status": "completed",
        "priority": 2,
        "task_type": "task",
        "complexity": "STANDARD",
        "title": "Completed task",
    }

    output = format_toon_context(task, None, [], [])

    assert "FRESHNESS:" not in output
