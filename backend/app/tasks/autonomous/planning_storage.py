"""Database storage operations for autonomous planning."""

from __future__ import annotations

from typing import Any

from ...logging_config import get_logger
from ...storage.subtasks import bulk_add_subtask_dependencies, bulk_create_subtasks
from ...storage.task_spirit import create_task_spirit, get_task_spirit, update_task_spirit

logger = get_logger(__name__)


def save_plan_to_database(task_id: str, plan_data: dict[str, Any]) -> None:
    """Save parsed plan to database using existing storage functions.

    Args:
        task_id: Task ID to save plan for
        plan_data: Parsed plan with objective, subtasks, and constraints
    """
    objective = plan_data.get("objective", "")
    subtasks_data = plan_data.get("subtasks", [])
    constraints = plan_data.get("constraints", [])

    # Create or update task spirit
    spirit = get_task_spirit(task_id)
    if not spirit:
        create_task_spirit(task_id=task_id, objective=objective, constraints=constraints)
    else:
        update_task_spirit(task_id, objective=objective, constraints=constraints)

    # Create subtasks
    if subtasks_data:
        formatted_subtasks: list[dict[str, Any]] = []
        for st in subtasks_data:
            steps = st.get("steps", [])
            formatted_steps = []
            for step in steps:
                if isinstance(step, dict):
                    formatted_steps.append(
                        {"description": step.get("description", "")}
                    )
                else:
                    formatted_steps.append({"description": str(step)})

            formatted_subtasks.append(
                {
                    "subtask_id": st.get("subtask_id", f"{len(formatted_subtasks) + 1}.1"),
                    "phase": st.get("phase"),
                    "subtask_type": st.get("subtask_type"),
                    "description": st.get("description", ""),
                    "steps": formatted_steps,
                }
            )

        bulk_create_subtasks(task_id, formatted_subtasks)
        logger.info("Created subtasks from plan", task_id=task_id, count=len(formatted_subtasks))

        # Store subtask dependencies from planner output
        deps: list[tuple[str, str]] = []
        for st in subtasks_data:
            sid = st.get("subtask_id", "")
            for dep in st.get("depends_on", []):
                if dep and sid:
                    deps.append((sid, dep))
        if deps:
            try:
                bulk_add_subtask_dependencies(task_id, deps)
                logger.info("Created subtask dependencies", task_id=task_id, count=len(deps))
            except Exception as e:
                logger.warning("Failed to create dependencies", task_id=task_id, error=str(e))
