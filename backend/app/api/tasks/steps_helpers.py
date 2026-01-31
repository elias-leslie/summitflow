"""Helper functions for step management.

This module contains utility functions used by the steps API endpoints.
"""

from __future__ import annotations

from typing import Any


def get_subtask_table_id(task_id: str, subtask_id: str) -> str:
    """Generate the subtask table ID.

    Format: {task_id}-{subtask_id} e.g., "task-abc123-1.1"

    Args:
        task_id: Task ID
        subtask_id: Subtask ID (e.g., "1.1")

    Returns:
        Subtask table ID string
    """
    return f"{task_id}-{subtask_id}"


def get_verification_cwd(project_id: str, task_id: str) -> str | None:
    """Get the working directory for step verification.

    Returns the project root path for verification commands.

    Args:
        project_id: Project ID
        task_id: Task ID (unused, kept for API compatibility)

    Returns:
        Path to use as cwd for verification commands
    """
    from ...storage.projects import get_project_root_path

    return get_project_root_path(project_id)


def convert_steps_to_storage_format(
    steps: list[str | Any],
) -> list[str | dict[str, Any]]:
    """Convert BatchStepCreate.steps to storage format.

    Handles both strings and StepInput objects.

    Args:
        steps: List of step descriptions (strings or StepInput objects)

    Returns:
        List of steps in storage format (strings or dicts)
    """
    result: list[str | dict[str, Any]] = []
    for step in steps:
        if isinstance(step, str):
            result.append(step)
        else:
            # StepInput object - convert to dict
            result.append({"description": step.description, "spec": step.spec})
    return result
