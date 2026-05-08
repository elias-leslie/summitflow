"""Shared ranking for execution-ready task pickup."""

from __future__ import annotations

from datetime import datetime
from typing import Any

_COMPLEXITY_ORDER = {
    "SIMPLE": 0,
    "STANDARD": 1,
    "COMPLEX": 3,
}

_TYPE_ORDER = {
    "bug": 0,
    "regression": 0,
    "refactor": 1,
    "debt": 1,
    "task": 2,
    "test": 2,
    "docs": 2,
    "chore": 2,
    "feature": 4,
}


def _int_value(value: object, default: int = 0) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _remaining_subtasks(task: dict[str, Any]) -> int:
    summary = task.get("subtask_summary")
    if not isinstance(summary, dict):
        return 0
    total = _int_value(summary.get("total"))
    completed = _int_value(summary.get("completed"))
    return max(total - completed, 0)


def _created_sort_value(task: dict[str, Any]) -> str:
    value = task.get("created_at")
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "")


def ready_task_sort_key(task: dict[str, Any]) -> tuple[int, int, int, int, int, str, str]:
    """Rank ready work for sequential pickup."""
    complexity = str(task.get("complexity") or "STANDARD").upper()
    task_type = str(task.get("task_type") or "task").lower()
    return (
        -_int_value(task.get("blocking_count")),
        _COMPLEXITY_ORDER.get(complexity, _COMPLEXITY_ORDER["STANDARD"]),
        _int_value(task.get("priority"), 2),
        _TYPE_ORDER.get(task_type, _TYPE_ORDER["task"]),
        _remaining_subtasks(task),
        _created_sort_value(task),
        str(task.get("id") or ""),
    )


def sort_ready_tasks(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return ready tasks in autonomous pickup order."""
    return sorted(tasks, key=ready_task_sort_key)
