"""Subtask creation for autonomous tasks."""

from __future__ import annotations

from app.storage.subtasks import bulk_create_subtasks
from app.tasks.subtask_builder import create_single_subtask_with_steps

__all__ = ["create_architecture_subtasks", "create_single_subtask_with_steps"]


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
