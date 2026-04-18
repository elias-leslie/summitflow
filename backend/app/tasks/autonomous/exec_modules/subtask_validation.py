"""Validation logic for subtask execution environment."""

from __future__ import annotations

from typing import Any

from .checkout import check_checkout_health
from .events import emit_log


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
    if not check_checkout_health(project_path, task_id, project_id):
        return {
            "subtask_id": subtask_short_id,
            "status": "failed",
            "reason": "checkout_invalid",
        }

    steps = subtask.get("steps_from_table") or subtask.get("steps") or []
    if not steps:
        emit_log(
            task_id,
            "info",
            f"Subtask {subtask_short_id} has 0 steps — will use smoke tests only",
            source="orchestrator",
            project_id=project_id,
        )

    return None
