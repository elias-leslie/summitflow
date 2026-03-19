"""Subtask creation for autonomous tasks."""

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
        steps: Ignored (steps layer removed)
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
        }
    ]
    created_subtasks = bulk_create_subtasks(task_id, subtask_data)

    if not created_subtasks:
        return None

    return cast(str, created_subtasks[0]["id"])


def create_architecture_subtasks(
    task_id: str,
    violation_type: str,
    affected_files: list[str],
) -> None:
    """Create subtasks for architecture violations.

    Args:
        task_id: Task ID
        violation_type: Type of violation
        affected_files: List of affected files
    """
    subtask_data = []
    for i, file_path in enumerate(affected_files[:10], 1):
        subtask_data.append(
            {
                "subtask_id": f"1.{i}",
                "phase": "backend" if file_path.endswith(".py") else "frontend",
                "description": f"Fix {violation_type.replace('_', ' ')} in {file_path.split('/')[-1]}",
                "subtask_type": "refactor",
            }
        )

    if not subtask_data:
        return

    bulk_create_subtasks(task_id, subtask_data)
