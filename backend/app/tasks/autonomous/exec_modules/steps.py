"""Step verification and step-related utilities.

This module re-exports functions from specialized submodules and provides
high-level verification orchestration.
"""

from __future__ import annotations

from typing import Any

from ....storage.steps import get_steps_for_subtask, update_step_passes
from .step_defect import (
    INFRASTRUCTURE_PATTERNS,
    auto_defect_step,
    is_infrastructure_failure,
)
from .step_issue import compute_issue_id
from .step_smoke_tests import run_smoke_and_targeted_tests
from .step_verification import verify_single_step

__all__ = [
    "INFRASTRUCTURE_PATTERNS",
    "auto_defect_step",
    "compute_issue_id",
    "is_infrastructure_failure",
    "reset_steps_for_rerun",
    "verify_steps",
    "verify_steps_with_smoke_tests",
]


def reset_steps_for_rerun(subtasks: list[dict[str, Any]]) -> None:
    """Reset step passes values to allow re-running failed tasks.

    Called at the start of execution to clear previous verification results.
    This enables running the same task multiple times without stale state.
    """
    for subtask in subtasks:
        subtask_table_id = subtask.get("id", "")
        if not subtask_table_id:
            continue

        steps = get_steps_for_subtask(subtask_table_id)
        for step in steps:
            if step.get("passes"):
                update_step_passes(subtask_table_id, step["step_number"], passes=False)


def verify_steps(
    task_id: str,
    subtask_id: str,
    steps: list[dict[str, Any]],
    project_path: str,
    project_id: str,
) -> list[dict[str, Any]]:
    """Run verify_command for each step and check exit code.

    Short-circuits: once a step fails, remaining steps are skipped.
    Steps already marked plan_defect are also skipped.
    """
    results: list[dict[str, Any]] = []
    first_failed: int | None = None

    for step in steps:
        result = verify_single_step(
            step, task_id, subtask_id, project_path, project_id, first_failed
        )
        results.append(result)

        if not result["passed"] and first_failed is None:
            first_failed = result["step_number"]

    return results


def verify_steps_with_smoke_tests(
    task_id: str,
    subtask_id: str,
    steps: list[dict[str, Any]],
    project_path: str,
    project_id: str,
) -> tuple[bool, list[dict[str, Any]]]:
    """Verify steps and run smoke tests on changed files.

    Returns:
        Tuple of (all_passed, step_results)
    """
    step_results = verify_steps(task_id, subtask_id, steps, project_path, project_id)
    all_passed = all(r["passed"] for r in step_results)

    # Run smoke tests and targeted tests if explicit verification passed
    if all_passed:
        all_passed = run_smoke_and_targeted_tests(
            task_id, project_path, project_id, step_results
        )

    return all_passed, step_results
