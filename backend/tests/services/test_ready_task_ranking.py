"""Tests for ready task pickup ranking."""

from __future__ import annotations

from app.services.ready_task_ranking import sort_ready_tasks


def test_sort_ready_tasks_prefers_smaller_work_before_complex_features() -> None:
    tasks = [
        {
            "id": "task-complex-p1",
            "priority": 1,
            "task_type": "feature",
            "complexity": "COMPLEX",
        },
        {
            "id": "task-simple-p2",
            "priority": 2,
            "task_type": "refactor",
            "complexity": "SIMPLE",
        },
        {
            "id": "task-standard-p0",
            "priority": 0,
            "task_type": "bug",
            "complexity": "STANDARD",
        },
    ]

    assert [task["id"] for task in sort_ready_tasks(tasks)] == [
        "task-simple-p2",
        "task-standard-p0",
        "task-complex-p1",
    ]


def test_sort_ready_tasks_uses_priority_inside_complexity_band() -> None:
    tasks = [
        {"id": "task-simple-p2", "priority": 2, "task_type": "bug", "complexity": "SIMPLE"},
        {"id": "task-simple-p1", "priority": 1, "task_type": "refactor", "complexity": "SIMPLE"},
    ]

    assert [task["id"] for task in sort_ready_tasks(tasks)] == [
        "task-simple-p1",
        "task-simple-p2",
    ]


def test_sort_ready_tasks_promotes_tasks_that_unblock_other_work() -> None:
    tasks = [
        {
            "id": "task-simple-unrelated",
            "priority": 2,
            "task_type": "bug",
            "complexity": "SIMPLE",
            "blocking_count": 0,
        },
        {
            "id": "task-baseline-blocker",
            "priority": 1,
            "task_type": "bug",
            "complexity": "STANDARD",
            "blocking_count": 1,
        },
    ]

    assert [task["id"] for task in sort_ready_tasks(tasks)] == [
        "task-baseline-blocker",
        "task-simple-unrelated",
    ]


def test_sort_ready_tasks_demotes_generic_feedback_upkeep_behind_scoped_work() -> None:
    tasks = [
        {
            "id": "task-generic-feedback",
            "priority": 2,
            "task_type": "bug",
            "complexity": "SIMPLE",
            "title": "Handle feedback: historical tool failure",
            "description": "Routine upkeep selected this active feedback item for resolution.",
        },
        {
            "id": "task-refactor",
            "priority": 2,
            "task_type": "refactor",
            "complexity": "SIMPLE",
            "title": "[TRIAGE] Refactor: backend/app/services/example.py",
            "description": "Extract helper from example.py.",
        },
    ]

    assert [task["id"] for task in sort_ready_tasks(tasks)] == [
        "task-refactor",
        "task-generic-feedback",
    ]


def test_sort_ready_tasks_does_not_let_generic_simple_feedback_starve_refactors() -> None:
    tasks = [
        {
            "id": "task-generic-feedback",
            "priority": 2,
            "task_type": "bug",
            "complexity": "SIMPLE",
            "title": "Handle feedback: stale command failure",
            "description": "Routine upkeep selected this active feedback item for resolution.",
        },
        {
            "id": "task-standard-refactor",
            "priority": 2,
            "task_type": "refactor",
            "complexity": "STANDARD",
            "title": "[TRIAGE] Refactor: backend/app/services/example.py",
            "description": "Extract cohesive helpers from example.py.",
        },
    ]

    assert [task["id"] for task in sort_ready_tasks(tasks)] == [
        "task-standard-refactor",
        "task-generic-feedback",
    ]
