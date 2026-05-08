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
