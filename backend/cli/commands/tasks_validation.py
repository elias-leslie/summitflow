"""Validation helpers for task commands."""

from __future__ import annotations

from typing import Any

from app.constants import TASK_TYPE_VALUES


def validate_task_item(item: dict[str, Any], index: int) -> list[str]:
    """Validate a single task item and return list of errors."""
    errors: list[str] = []
    prefix = f"tasks[{index}]"
    if "title" not in item or not item["title"]:
        errors.append(f"{prefix}: Missing required field 'title'")
    if "task_type" not in item or not item["task_type"]:
        errors.append(f"{prefix}: Missing required field 'task_type'")
    valid_types = TASK_TYPE_VALUES
    if item.get("task_type") and item["task_type"] not in valid_types:
        errors.append(f"{prefix}: task_type must be one of: {', '.join(valid_types)}")
    if "priority" in item:
        p = item["priority"]
        if not isinstance(p, int) or p < 0 or p > 4:
            errors.append(f"{prefix}: priority must be integer 0-4")
    for si, subtask in enumerate(item.get("subtasks") or []):
        sub_prefix = f"{prefix}.subtasks[{si}]"
        if "subtask_id" not in subtask:
            errors.append(f"{sub_prefix}: Missing required field 'subtask_id'")
        if "description" not in subtask:
            errors.append(f"{sub_prefix}: Missing required field 'description'")
    return errors


def _validate_complexity(plan: dict[str, Any]) -> list[str]:
    """Validate conditional requirements based on complexity."""
    issues: list[str] = []
    complexity = plan.get("complexity", "SIMPLE")
    if complexity in ("STANDARD", "COMPLEX") and not plan.get("done_when"):
        issues.append(f"Conditional: {complexity} tasks require 'done_when' with at least 1 item")
    return issues


def _validate_subtask_deps(subtasks: list[dict], valid_ids: set) -> list[str]:
    """Validate depends_on references are valid and non-self-referential."""
    issues: list[str] = []
    for subtask in subtasks:
        subtask_id = subtask.get("id", "?")
        raw_depends_on = subtask.get("depends_on")
        if "depends_on" in subtask and not isinstance(raw_depends_on, list):
            issues.append(f"subtask {subtask_id} depends_on must be an array")
            continue
        for dep in raw_depends_on or []:
            if dep not in valid_ids:
                issues.append(f"subtask {subtask_id} depends_on '{dep}' which doesn't exist")
            if dep == subtask_id:
                issues.append(f"subtask {subtask_id} cannot depend on itself")
    return issues


def validate_plan_schema(plan: dict[str, Any]) -> list[str]:
    """Validate plan structure and return list of issues."""
    subtasks = plan.get("subtasks", [])
    issues = _validate_complexity(plan)
    if not subtasks:
        return issues
    valid_ids = {s.get("id") for s in subtasks if s.get("id")}
    issues += _validate_subtask_deps(subtasks, valid_ids)
    return issues
