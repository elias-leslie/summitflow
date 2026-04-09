"""Subtask CRUD operations - Create, Read, Update, Delete for subtasks.

This module provides basic database operations for the task_subtasks table.
All functions use short subtask IDs (e.g., "1.1") and convert to table IDs internally.
"""

from __future__ import annotations

from ..logging_config import get_logger
from .connection import get_cursor
from .subtasks_helpers import SUBTASK_COLUMNS, generate_subtask_id, row_to_dict

logger = get_logger(__name__)


def _attach_plan_context_guidance(
    task_id: str,
    subtasks: list[dict[str, object]],
) -> None:
    """Hydrate plan-only step guidance from task_spirit.context when step rows do not exist."""
    from ..services.task_plan_context import get_plan_subtask_map
    from .task_spirit import get_task_spirit

    spirit = get_task_spirit(task_id)
    if not spirit:
        return

    subtask_map = get_plan_subtask_map(spirit.get("context"))
    if not subtask_map:
        return

    for subtask in subtasks:
        if subtask.get("steps_from_table"):
            continue
        spec = subtask_map.get(str(subtask.get("subtask_id", "")))
        if not spec:
            continue
        guidance_steps = spec.get("steps")
        if not isinstance(guidance_steps, list) or not guidance_steps:
            continue
        subtask["steps"] = guidance_steps
        subtask["steps_source"] = "plan_context"
        subtask["step_summary"] = {"total": len(guidance_steps), "completed": 0}


def _short_subtask_id(task_id: str, table_id: str) -> str:
    prefix = f"{task_id}-"
    if table_id.startswith(prefix):
        return table_id[len(prefix):]
    return table_id


def _attach_dependencies(task_id: str, subtasks: list[dict[str, object]]) -> None:
    """Hydrate each subtask with its short-id dependency list."""
    from .subtask_dependencies import get_all_dependencies_for_task

    dependency_map = {
        str(subtask.get("subtask_id", "")): [] for subtask in subtasks if subtask.get("subtask_id")
    }
    for dependency in get_all_dependencies_for_task(task_id):
        subtask_id = _short_subtask_id(task_id, str(dependency.get("subtask_id", "")))
        depends_on = _short_subtask_id(task_id, str(dependency.get("depends_on_subtask_id", "")))
        if not subtask_id or not depends_on:
            continue
        dependency_map.setdefault(subtask_id, []).append(depends_on)

    for subtask in subtasks:
        subtask_id = str(subtask.get("subtask_id", ""))
        subtask["depends_on"] = dependency_map.get(subtask_id, [])


def get_subtask(task_id: str, subtask_id: str) -> dict[str, object] | None:
    """Get a single subtask by task_id and subtask_id.

    Returns:
        Subtask dict or None if not found.
    """
    table_id = generate_subtask_id(task_id, subtask_id)

    with get_cursor() as cur:
        cur.execute(
            f"SELECT {SUBTASK_COLUMNS} FROM task_subtasks WHERE id = %s",
            (table_id,),
        )
        row = cur.fetchone()

    if not row:
        return None
    return row_to_dict(row)


def get_subtask_by_table_id(table_id: str) -> dict[str, object] | None:
    """Get a single subtask by its full table ID.

    Args:
        table_id: Full subtask ID (e.g., "task-abc123-1.1")

    Returns:
        Subtask dict or None if not found.
    """
    with get_cursor() as cur:
        cur.execute(
            f"SELECT {SUBTASK_COLUMNS} FROM task_subtasks WHERE id = %s",
            (table_id,),
        )
        row = cur.fetchone()

    if not row:
        return None
    return row_to_dict(row)


def get_subtasks_for_task(
    task_id: str, include_steps: bool = False
) -> list[dict[str, object]]:
    """Get all subtasks for a task, ordered by display_order.

    Args:
        task_id: Parent task ID
        include_steps: If True, include steps from task_subtask_steps table

    Returns:
        List of subtask dicts, ordered by display_order.
    """
    with get_cursor() as cur:
        cur.execute(
            f"""
            SELECT {SUBTASK_COLUMNS}
            FROM task_subtasks
            WHERE task_id = %s
            ORDER BY display_order
            """,
            (task_id,),
        )
        rows = cur.fetchall()

    subtasks = [row_to_dict(row) for row in rows]
    _attach_dependencies(task_id, subtasks)

    if include_steps:
        for subtask in subtasks:
            subtask["steps_from_table"] = []
            subtask["step_summary"] = {"total": 0, "completed": 0}
        _attach_plan_context_guidance(task_id, subtasks)

    return subtasks
