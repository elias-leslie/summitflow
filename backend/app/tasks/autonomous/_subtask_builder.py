"""Subtask and step creation for autonomous tasks."""

from __future__ import annotations

from typing import cast

from app.storage.steps import bulk_create_steps
from app.storage.subtasks import bulk_create_subtasks


def create_single_subtask_with_steps(
    task_id: str,
    subtask_id: str,
    phase: str,
    description: str,
    steps: list[dict[str, str]],
) -> str | None:
    """Create a single subtask with its steps.

    Args:
        task_id: Task ID
        subtask_id: Subtask ID (e.g., "1.1")
        phase: Phase name (e.g., "backend", "frontend")
        description: Subtask description
        steps: List of step dictionaries

    Returns:
        Subtask full ID or None if creation failed
    """
    subtask_data = [
        {
            "subtask_id": subtask_id,
            "phase": phase,
            "description": description,
        }
    ]
    created_subtasks = bulk_create_subtasks(task_id, subtask_data)

    if not created_subtasks:
        return None

    subtask_full_id = cast(str, created_subtasks[0]["id"])
    bulk_create_steps(subtask_full_id, steps)
    return subtask_full_id


def create_architecture_subtasks(
    task_id: str,
    violation_type: str,
    affected_files: list[str],
) -> None:
    """Create subtasks and steps for architecture violations.

    Args:
        task_id: Task ID
        violation_type: Type of violation
        affected_files: List of affected files
    """
    # Limit to first 10 files to avoid overload
    subtask_data = []
    for i, file_path in enumerate(affected_files[:10], 1):
        subtask_data.append(
            {
                "subtask_id": f"1.{i}",
                "phase": "backend" if file_path.endswith(".py") else "frontend",
                "description": f"Fix {violation_type.replace('_', ' ')} in {file_path.split('/')[-1]}",
            }
        )

    if not subtask_data:
        return

    created_subtasks = bulk_create_subtasks(task_id, subtask_data)

    for idx, subtask in enumerate(created_subtasks):
        subtask_full_id = cast(str, subtask["id"])
        file = affected_files[idx] if idx < len(affected_files) else ""
        steps = [
            {
                "description": f"Identify {violation_type.replace('_', ' ')} issue",
                "verify_command": f"test -f {file}" if file else "",
            },
            {
                "description": "Implement fix following project patterns",
                "verify_command": "dt --quick --changed-only",
            },
            {
                "description": "Verify fix with full quality gates",
                "verify_command": "dt --check",
            },
        ]
        bulk_create_steps(subtask_full_id, steps)
