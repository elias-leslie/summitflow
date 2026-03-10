"""Step utilities and quality check orchestration.

This module provides step management and quality verification
via smoke tests and targeted tests.
"""

from __future__ import annotations

import subprocess
from typing import Any

from ....logging_config import get_logger
from ....storage.steps import get_steps_for_subtask, update_step_passes
from ....storage.task_spirit import get_task_spirit
from ....storage.tasks import get_task
from .step_defect import (
    INFRASTRUCTURE_PATTERNS,
    auto_defect_step,
    is_infrastructure_failure,
)
from .step_issue import compute_issue_id
from .step_smoke_tests import run_smoke_and_targeted_tests

logger = get_logger(__name__)

_NO_CODE_MARKERS = (
    "no code edits",
    "no product code edits",
    "do not modify product code",
    "workflow validation only",
    "workflow-only",
    "temporary validation task only",
)

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


def _auto_mark_steps(
    subtask_id: str,
    steps: list[dict[str, Any]],
    project_id: str,
    plan_defect_status: str,
) -> list[dict[str, Any]]:
    """Auto-mark all steps as passed, skipping plan-defect steps.

    Returns a list of step result dicts ready for smoke-test verification.
    """
    step_results: list[dict[str, Any]] = []
    for step in steps:
        step_num = step.get("step_number", 0)
        status = step.get("status", "")
        if status == plan_defect_status:
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
    return step_results


def _has_work_product(project_path: str) -> bool:
    """Check if the worktree contains branch-local work to verify.

    Agents typically edit first and validate before anything is committed, so
    uncommitted tracked changes in the task worktree count as legitimate work
    product alongside branch-local commits.
    """
    try:
        commits = subprocess.run(
            ["git", "log", "--oneline", "main..HEAD"],
            cwd=project_path, capture_output=True, text=True, timeout=10,
        )
        if commits.stdout and commits.stdout.strip():
            return True

        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=project_path, capture_output=True, text=True, timeout=10,
        )
        return bool(status.stdout and status.stdout.strip())
    except (subprocess.TimeoutExpired, OSError):
        # If we can't check, assume work product exists to avoid false negatives
        return True


def _allows_no_code_verification(task_id: str) -> bool:
    """Return True when a task is explicitly scoped as workflow/no-code validation."""
    task = get_task(task_id) or {}
    spirit = get_task_spirit(task_id) or {}

    fields = [
        task.get("title", ""),
        task.get("description", ""),
        spirit.get("objective", ""),
        spirit.get("spirit_anti", ""),
        *(spirit.get("constraints") or []),
        *(spirit.get("done_when") or []),
    ]
    haystack = " ".join(str(field).lower() for field in fields if field)
    return any(marker in haystack for marker in _NO_CODE_MARKERS)


def run_execution_quality_check(
    task_id: str,
    subtask_id: str,
    steps: list[dict[str, Any]],
    project_path: str,
    project_id: str,
) -> tuple[bool, list[dict[str, Any]]]:
    """Run quality check: auto-mark steps passed, then run smoke/targeted tests.

    Steps are progress trackers (auto-marked passed), and smoke/targeted tests
    are the primary verification signal. If no commits exist on the branch,
    the last step is marked FAILED to prevent false completions.

    Returns:
        Tuple of (all_passed, step_results)
    """
    from ....storage.steps_constants import STEP_STATUS_PLAN_DEFECT

    step_results = _auto_mark_steps(subtask_id, steps, project_id, STEP_STATUS_PLAN_DEFECT)

    # Fail if no work product exists unless the task is explicitly no-code validation.
    if not _has_work_product(project_path) and not _allows_no_code_verification(task_id):
        logger.warning("No commits on branch — marking as failed",
                        task_id=task_id, subtask_id=subtask_id)
        if step_results:
            step_results[-1]["passed"] = False
            step_results[-1]["reason"] = "no_work_product"
            step_results[-1]["output"] = "No commits found on branch beyond main"
        return False, step_results

    # Run smoke tests and targeted tests as primary verification
    all_passed = run_smoke_and_targeted_tests(
        task_id, project_path, project_id, step_results
    )

    if not all_passed and step_results:
        # Mark last step as failed to trigger healing loop
        step_results[-1]["passed"] = False
        step_results[-1]["reason"] = "smoke_test_failure"

    return all_passed, step_results
