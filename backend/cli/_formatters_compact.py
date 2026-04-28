"""Compact one-liner formatters for tasks, subtasks, and dependencies."""

from __future__ import annotations

from typing import cast


def truncate(s: str, length: int) -> str:
    """Truncate string to length, adding ... if truncated."""
    if len(s) <= length:
        return s
    return s[: length - 3] + "..."


def _safe_int(value: object) -> int:
    """Convert value to int safely; returns 0 for non-numeric or invalid values."""
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        try:
            return int(float(value))
        except (ValueError, TypeError):
            return 0
    return 0


def format_compact_task(task: dict[str, object]) -> str:
    """Format task as compact one-liner."""
    priority = task.get("priority", 3)
    task_id = task.get("id", "unknown")
    project_id = task.get("project_id") or ""
    task_type = (str(task.get("task_type") or "task"))[:10].ljust(10)
    status = (str(task.get("status") or "pending"))[:7].ljust(7)
    triage = "[TRIAGE] " if not task.get("objective") and not task.get("complexity") else ""
    title = truncate(str(task.get("title") or ""), 50 - len(triage))
    return f"P{priority} {task_id} {project_id!s:12} {task_type} {status} {triage}{title}"


def format_compact_subtask(subtask: dict[str, object]) -> str:
    """Format subtask as compact one-liner."""
    subtask_id = subtask.get("subtask_id", "?")
    passes = "PASS" if subtask.get("passes") else "____"
    description = truncate(str(subtask.get("description") or ""), 40)
    raw_step_summary = subtask.get("step_summary")
    step_summary = cast(dict[str, object], raw_step_summary) if isinstance(raw_step_summary, dict) else {}
    done = _safe_int(step_summary.get("completed", 0))
    total = _safe_int(step_summary.get("total", 0))
    return f"{subtask_id:5} {passes} {description:40} [{done}/{total}]"


def format_compact_dep(dep: dict[str, object]) -> str:
    """Format dependency as compact one-liner."""
    from_id = dep.get("from_task_id", "?")
    to_id = dep.get("to_task_id", "?")
    dep_type = (str(dep.get("dependency_type") or "blocks"))[:6].ljust(6)
    return f"{from_id} {dep_type} {to_id}"
