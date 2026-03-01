"""Database storage operations for autonomous planning."""

from __future__ import annotations

from typing import Any

from ...logging_config import get_logger
from ...storage.subtasks import bulk_add_subtask_dependencies, bulk_create_subtasks
from ...storage.task_spirit import create_task_spirit, get_task_spirit, update_task_spirit

logger = get_logger(__name__)


def _format_step(step: Any) -> dict[str, str]:
    """Format a single step into a dict with a description field."""
    if isinstance(step, dict):
        return {"description": step.get("description", "")}
    return {"description": str(step)}


def _format_subtask(st: dict[str, Any], index: int) -> dict[str, Any]:
    """Format a single subtask entry for bulk creation."""
    steps = st.get("steps", [])
    formatted_steps = [_format_step(step) for step in steps]
    return {
        "subtask_id": st.get("subtask_id", f"{index}.1"),
        "phase": st.get("phase"),
        "subtask_type": st.get("subtask_type"),
        "description": st.get("description", ""),
        "steps": formatted_steps,
    }


def _collect_dependencies(subtasks_data: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """Collect all subtask dependency pairs from plan data."""
    deps: list[tuple[str, str]] = []
    for st in subtasks_data:
        sid = st.get("subtask_id", "")
        for dep in st.get("depends_on", []):
            if dep and sid:
                deps.append((sid, dep))
    return deps


def _upsert_task_spirit(
    task_id: str, objective: str, constraints: list[Any]
) -> None:
    """Create or update the task spirit record."""
    spirit = get_task_spirit(task_id)
    if not spirit:
        create_task_spirit(task_id=task_id, objective=objective, constraints=constraints)
    else:
        update_task_spirit(task_id, objective=objective, constraints=constraints)


def _create_subtasks_from_plan(
    task_id: str, subtasks_data: list[dict[str, Any]]
) -> None:
    """Create subtasks and their dependencies from plan data."""
    formatted_subtasks = [
        _format_subtask(st, i + 1) for i, st in enumerate(subtasks_data)
    ]
    bulk_create_subtasks(task_id, formatted_subtasks)
    logger.info("Created subtasks from plan", task_id=task_id, count=len(formatted_subtasks))

    deps = _collect_dependencies(subtasks_data)
    if not deps:
        return
    try:
        bulk_add_subtask_dependencies(task_id, deps)
        logger.info("Created subtask dependencies", task_id=task_id, count=len(deps))
    except Exception as e:
        logger.warning("Failed to create dependencies", task_id=task_id, error=str(e))


def save_plan_to_database(task_id: str, plan_data: dict[str, Any]) -> None:
    """Save parsed plan to database using existing storage functions.

    Args:
        task_id: Task ID to save plan for
        plan_data: Parsed plan with objective, subtasks, and constraints
    """
    objective = plan_data.get("objective", "")
    subtasks_data = plan_data.get("subtasks", [])
    constraints = plan_data.get("constraints", [])

    _upsert_task_spirit(task_id, objective, constraints)

    if subtasks_data:
        _create_subtasks_from_plan(task_id, subtasks_data)
