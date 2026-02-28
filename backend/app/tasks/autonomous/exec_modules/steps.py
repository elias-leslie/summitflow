"""Step utilities and quality check orchestration.

This module provides step management and quality verification
via smoke tests and targeted tests.
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

__all__ = [
    "INFRASTRUCTURE_PATTERNS",
    "auto_defect_step",
    "compute_issue_id",
    "is_infrastructure_failure",
    "reset_steps_for_rerun",
    "run_execution_quality_check",
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


def run_execution_quality_check(
    task_id: str,
    subtask_id: str,
    steps: list[dict[str, Any]],
    project_path: str,
    project_id: str,
) -> tuple[bool, list[dict[str, Any]]]:
    """Run quality check: auto-mark steps passed, then run smoke/targeted tests.

    This replaces the old verify_steps_with_smoke_tests flow. Steps are now
    progress trackers (auto-marked passed), and smoke/targeted tests are the
    primary verification signal.

    Returns:
        Tuple of (all_passed, step_results)
    """
    from ....storage.steps_constants import STEP_STATUS_PLAN_DEFECT

    step_results: list[dict[str, Any]] = []

    # Auto-mark all non-defect steps as passed
    for step in steps:
        step_num = step.get("step_number", 0)
        status = step.get("status", "")

        if status == STEP_STATUS_PLAN_DEFECT:
            step_results.append({
                "step_number": step_num,
                "passed": True,
                "output": "plan_defect — skipped",
                "reason": "plan_defect",
                "returncode": 0,
            })
            continue

        if not step.get("passes"):
            update_step_passes(subtask_id, step_num, passes=True, project_id=project_id)

        step_results.append({
            "step_number": step_num,
            "passed": True,
            "output": "",
            "reason": "auto_passed",
            "returncode": 0,
        })

    # Run smoke tests and targeted tests as primary verification
    all_passed = run_smoke_and_targeted_tests(
        task_id, project_path, project_id, step_results
    )

    if not all_passed and step_results:
        # Mark last step as failed to trigger healing loop
        step_results[-1]["passed"] = False
        step_results[-1]["reason"] = "smoke_test_failure"

    return all_passed, step_results
