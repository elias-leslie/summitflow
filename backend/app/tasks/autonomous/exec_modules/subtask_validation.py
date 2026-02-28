"""Validation logic for subtask execution environment."""

from __future__ import annotations

from typing import Any

from .events import emit_log
from .worktree import check_worktree_health


def validate_subtask_environment(
    task_id: str,
    subtask: dict[str, Any],
    subtask_short_id: str,
    project_path: str,
    project_id: str,
) -> dict[str, Any] | None:
    """Validate subtask environment before execution.

    Returns:
        Failure dict if validation fails, None if validation passes.
    """
    if not check_worktree_health(project_path, task_id, project_id):
        return {
            "subtask_id": subtask_short_id,
            "status": "failed",
            "reason": "worktree_invalid",
        }

    steps = subtask.get("steps_from_table", [])
    if not steps:
        emit_log(
            task_id,
            "info",
            f"Subtask {subtask_short_id} has 0 steps — will use smoke tests only",
            source="orchestrator",
            project_id=project_id,
        )

    return None
