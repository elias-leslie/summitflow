"""Helpers for mirroring rich subtask metadata into task_spirit.context."""

from __future__ import annotations

from typing import Any

from ..services.task_plan_context import merge_plan_subtasks, remove_plan_subtasks
from .task_spirit import get_task_spirit, update_task_spirit, upsert_task_spirit


def _context_for_task(task_id: str) -> tuple[dict[str, Any], bool]:
    spirit = get_task_spirit(task_id)
    if spirit and isinstance(spirit.get("context"), dict):
        return {str(key): value for key, value in spirit["context"].items()}, True
    return {}, spirit is not None


def sync_subtasks_to_plan_context(task_id: str, subtasks: list[dict[str, Any]]) -> None:
    """Merge subtask metadata into task_spirit.context.subtasks."""
    if not subtasks:
        return
    context, spirit_exists = _context_for_task(task_id)
    merged = merge_plan_subtasks(context.get("subtasks"), subtasks)
    if not merged:
        return
    context["subtasks"] = merged
    if spirit_exists:
        update_task_spirit(task_id, context=context)
    else:
        upsert_task_spirit(task_id=task_id, context=context)


def remove_subtasks_from_plan_context(task_id: str, subtask_ids: list[str]) -> None:
    """Remove subtask metadata from task_spirit.context.subtasks."""
    if not subtask_ids:
        return
    context, spirit_exists = _context_for_task(task_id)
    if not spirit_exists:
        return
    remaining = remove_plan_subtasks(context.get("subtasks"), subtask_ids)
    if remaining:
        context["subtasks"] = remaining
    else:
        context.pop("subtasks", None)
    update_task_spirit(task_id, context=context)
