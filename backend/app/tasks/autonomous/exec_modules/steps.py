"""Step verification and step-related utilities."""

from __future__ import annotations

import hashlib
import re
from typing import Any

from ....logging_config import get_logger
from ....storage.steps import get_steps_for_subtask, update_step_passes, update_step_status
from ....storage.steps_crud import append_steps
from ..verification import run_smoke_tests, verify_step
from .events import emit_log, emit_progress

logger = get_logger(__name__)


INFRASTRUCTURE_PATTERNS = [
    "command not found",
    "No such file or directory",
    "Permission denied",
    "not recognized as",
    "cannot execute binary",
    "is not installed",
    "ModuleNotFoundError",
    "ImportError: cannot import",
    "ImportError while loading",
    "FileNotFoundError",
    "timed out",
    "Connection refused",
]


def is_infrastructure_failure(output: str, reason: str, returncode: int) -> bool:
    """Classify whether a step failure is infrastructure (plan defect) vs code."""
    combined = f"{output}\n{reason}".lower()
    return any(pat.lower() in combined for pat in INFRASTRUCTURE_PATTERNS)


def auto_defect_step(
    subtask_id: str,
    step_number: int,
    output: str,
    task_id: str,
    project_id: str,
) -> bool:
    """Auto-mark an infrastructure failure as plan_defect.

    Creates a "no-op" fix step that passes (echo OK), marks it passed,
    then marks the original step as plan_defect pointing to the fix step.

    Returns True if auto-defect succeeded.
    """
    try:
        fix_steps = append_steps(subtask_id, [{
            "description": f"Fix: auto-defect for step {step_number} (infrastructure failure)",
            "verify_command": "true",
        }])
        if not fix_steps:
            return False

        fix_step_num: int = fix_steps[0]["step_number"]

        update_step_passes(subtask_id, fix_step_num, passes=True, project_id=project_id)

        update_step_status(
            subtask_id, step_number, status="plan_defect", fix_step_number=fix_step_num
        )

        emit_log(
            task_id,
            "warn",
            f"Step {step_number} auto-defected (infrastructure failure → fix step {fix_step_num})",
            source="orchestrator",
            project_id=project_id,
        )
        return True
    except Exception as e:
        logger.warning(
            "auto_defect_failed",
            subtask_id=subtask_id,
            step_number=step_number,
            error=str(e),
        )
        return False


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


def compute_issue_id(error: str) -> str:
    """Normalize error to stable ID for stuck detection."""
    normalized = re.sub(r":\d+:", ":N:", error)
    normalized = re.sub(r"/home/\w+/", "/HOME/", normalized)
    normalized = re.sub(r"\d{4}-\d{2}-\d{2}", "DATE", normalized)
    return hashlib.md5(normalized.encode()).hexdigest()[:8]


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
        step_num = step.get("step_number", 0)
        step_desc = step.get("description", "")[:50]

        if step.get("status") == "plan_defect":
            results.append({
                "step_number": step_num,
                "passed": True,
                "output": "plan_defect — skipped",
                "reason": "",
                "returncode": 0,
            })
            continue

        if first_failed is not None:
            emit_log(
                task_id, "info",
                f"Step {step_num} ({step_desc}): skipped (step {first_failed} failed)",
                source="verify", project_id=project_id,
            )
            results.append({
                "step_number": step_num,
                "passed": False,
                "output": f"Skipped: prerequisite step {first_failed} failed",
                "reason": f"skipped:prerequisite_step_{first_failed}_failed",
                "returncode": -1,
            })
            continue

        result = verify_step(step, project_path, project_id=project_id)

        update_step_passes(
            subtask_id, step_num, result.passed,
            project_root=project_path, already_verified=True,
        )
        status = "passed" if result.passed else "failed"

        verify_cmd = (step.get("verify_command") or "")[:60]
        output_preview = result.output[:200] if result.output else "(no output)"

        emit_log(
            task_id,
            "info" if result.passed else "warn",
            f"Step {step_num} ({step_desc}): {status}",
            source="verify",
            project_id=project_id,
        )

        emit_log(
            task_id, "debug", f"  cmd: {verify_cmd}",
            source="verify", project_id=project_id, visibility="internal",
        )
        emit_log(
            task_id,
            "debug" if result.passed else "warn",
            f"  output: {output_preview}",
            source="verify", project_id=project_id,
        )
        if not result.passed and result.reason:
            emit_log(
                task_id, "warn", f"  reason: {result.reason}",
                source="verify", project_id=project_id,
            )

        emit_progress(
            task_id, subtask_id=subtask_id, step=step_num, status=status, project_id=project_id
        )

        results.append({
            "step_number": step_num,
            "passed": result.passed,
            "output": result.output[:500],
            "reason": result.reason,
            "returncode": result.returncode,
        })

        if not result.passed:
            first_failed = step_num

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

    # Run smoke tests on changed files after explicit verification passes
    if all_passed:
        emit_log(
            task_id,
            "info",
            "Running smoke tests on changed files...",
            source="verify",
            project_id=project_id,
        )
        smoke_result = run_smoke_tests(project_path, project_id=project_id)
        if not smoke_result.passed:
            all_passed = False
            for failure in smoke_result.failures:
                step_results.append(
                    {
                        "step_number": 999,
                        "passed": False,
                        "output": f"Import failed: {failure['error']}",
                        "reason": f"smoke_test_failed:{failure['module']}",
                        "returncode": 1,
                    }
                )
                emit_log(
                    task_id,
                    "error",
                    f"Smoke test failed: {failure['module']} - {failure['error'][:100]}",
                    source="verify",
                    project_id=project_id,
                )
        else:
            tested_count = len(smoke_result.files_tested)
            if tested_count > 0:
                emit_log(
                    task_id,
                    "info",
                    f"Smoke tests passed ({tested_count} modules)",
                    source="verify",
                    project_id=project_id,
                )

    return all_passed, step_results
