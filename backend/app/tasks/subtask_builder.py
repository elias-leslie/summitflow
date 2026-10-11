"""Single-subtask creation helper shared by task-creating maintenance jobs."""

from __future__ import annotations

from typing import cast

from app.storage.subtasks import bulk_create_subtasks


def create_single_subtask_with_steps(
    task_id: str,
    subtask_id: str,
    phase: str,
    description: str,
    steps: list[dict[str, object]] | None = None,
    subtask_type: str | None = None,
) -> str | None:
    """Create a single subtask.

    Args:
        task_id: Task ID
        subtask_id: Subtask ID (e.g., "1.1")
        phase: Phase name (e.g., "backend", "frontend")
        description: Subtask description
        steps: Optional rich step guidance mirrored into task_spirit.context
        subtask_type: Optional subtask type

    Returns:
        Subtask full ID or None if creation failed
    """
    subtask_data = [
        {
            "subtask_id": subtask_id,
            "phase": phase,
            "description": description,
            "subtask_type": subtask_type,
            "steps": steps,
        }
    ]
    created_subtasks = bulk_create_subtasks(task_id, subtask_data)

    if not created_subtasks:
        return None

    return cast(str, created_subtasks[0]["id"])
