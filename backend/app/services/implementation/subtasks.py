"""Implementation subtasks - Subtask iteration and step tracking.

Handles getting next incomplete subtask and tracking step completion.
"""

from __future__ import annotations

from typing import Any

from ...logging_config import get_logger
from ...storage.subtasks import get_subtasks_for_task

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
