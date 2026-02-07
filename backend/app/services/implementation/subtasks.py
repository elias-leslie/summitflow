"""Implementation subtasks - Subtask iteration and step tracking.

Handles getting next incomplete subtask and tracking step completion.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ...logging_config import get_logger
from ...storage.steps import update_step_passes
from ...storage.subtasks import get_subtasks_for_task, update_subtask_passes

logger = get_logger(__name__)


def get_next_task_from_subtasks(
    task_id: str, completed_subtasks: set[str]
) -> dict[str, Any] | None:
    """Get the next incomplete subtask from the task_subtasks table.

    Args:
        task_id: Parent task ID
        completed_subtasks: Set of completed subtask IDs (format: "{subtask_id}")

    Returns:
        Dict with subtask info including steps, or None if all complete.
        Returns dict with keys: id, subtask_id, description, phase, steps
    """
    subtasks = get_subtasks_for_task(task_id, include_steps=True)
    if not subtasks:
        return None

    for subtask in subtasks:
        subtask_id = subtask.get("subtask_id", "")
        # Check if subtask is complete (either passes=True or in completed set)
        if subtask.get("passes"):
            continue
        if subtask_id in completed_subtasks:
            continue

        # Found incomplete subtask - get its steps
        full_id = subtask.get("id", "")  # e.g., "task-abc123-1.1"
        steps = subtask.get("steps") or []

        # Convert to execution format compatible with plan_content tasks
        return {
            "id": subtask_id,
            "subtask_full_id": full_id,
            "description": subtask.get("description", ""),
            "phase": subtask.get("phase", ""),
            "step_descriptions": [s.get("description", "") for s in steps],
            "steps": steps,  # Keep full step objects for tracking
            "display_order": subtask.get("display_order", 0),
        }

    return None


def mark_subtask_complete(
    current_task: dict[str, Any],
    repo_path: Path | str,
    project_id: str | None = None,
) -> None:
    """Mark subtask and its steps as complete."""
    subtask_full_id = current_task.get("subtask_full_id")
    if not subtask_full_id:
        return

    steps = current_task.get("steps") or []
    for step in steps:
        step_number = step.get("step_number")
        if step_number and not step.get("passes"):
            update_step_passes(
                subtask_full_id,
                step_number,
                True,
                project_root=str(repo_path),
                project_id=project_id,
            )
            logger.debug(
                "step_marked_complete",
                subtask_id=subtask_full_id,
                step_number=step_number,
            )

    match = re.match(r"^(.+)-(\d+\.\d+)$", subtask_full_id)
    if match:
        parsed_task_id, parsed_subtask_id = match.groups()
        update_subtask_passes(parsed_task_id, parsed_subtask_id, True)
        logger.info(
            "subtask_marked_complete",
            subtask_id=parsed_subtask_id,
            task_id=parsed_task_id,
        )
    else:
        logger.error("invalid_subtask_full_id_format", subtask_full_id=subtask_full_id)
