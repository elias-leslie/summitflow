"""Infrastructure failure handling for retry loop."""

from __future__ import annotations

from typing import Any

from .steps import auto_defect_step, is_infrastructure_failure


def handle_infrastructure_failures(
    failed_steps: list[dict[str, Any]],
    subtask_id: str,
    task_id: str,
    project_id: str,
) -> list[dict[str, Any]]:
    """Auto-defect infrastructure failures and return remaining failures.

    Args:
        failed_steps: List of failed step results
        subtask_id: ID of subtask being executed
        task_id: ID of parent task
        project_id: Project identifier

    Returns:
        List of failed steps after removing infrastructure failures
    """
    infra_failures = [
        f
        for f in failed_steps
        if is_infrastructure_failure(
            f.get("output", ""), f.get("reason", ""), f.get("returncode", 1)
        )
    ]

    if not infra_failures:
        return failed_steps

    for f in infra_failures:
        auto_defect_step(
            subtask_id,
            f["step_number"],
            f.get("output", ""),
            task_id,
            project_id,
        )

    return [f for f in failed_steps if f not in infra_failures]
