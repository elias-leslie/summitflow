"""Step verification core logic."""

from __future__ import annotations

from typing import Any

from ....storage.steps import update_step_passes
from ..verification import VerificationResult, verify_step
from .events import emit_log, emit_progress


def verify_single_step(
    step: dict[str, Any],
    task_id: str,
    subtask_id: str,
    project_path: str,
    project_id: str,
    first_failed: int | None,
) -> dict[str, Any]:
    """Verify a single step and emit logs/progress.

    Args:
        step: Step data including step_number, description, verify_command
        task_id: Task identifier
        subtask_id: Subtask identifier
        project_path: Path to project root
        project_id: Project identifier
        first_failed: Step number of first failed step (or None)

    Returns:
        Result dict with step_number, passed, output, reason, returncode
    """
    step_num = step.get("step_number", 0)
    step_desc = step.get("description", "")[:50]

    # Handle plan_defect status
    if step.get("status") == "plan_defect":
        return {
            "step_number": step_num,
            "passed": True,
            "output": "plan_defect — skipped",
            "reason": "",
            "returncode": 0,
        }

    # Handle prerequisite failure skip
    if first_failed is not None:
        emit_log(
            task_id,
            "info",
            f"Step {step_num} ({step_desc}): skipped (step {first_failed} failed)",
            source="verify",
            project_id=project_id,
        )
        return {
            "step_number": step_num,
            "passed": False,
            "output": f"Skipped: prerequisite step {first_failed} failed",
            "reason": f"skipped:prerequisite_step_{first_failed}_failed",
            "returncode": -1,
        }

    # Run verification
    result = verify_step(step, project_path, project_id=project_id)

    # Update database
    update_step_passes(
        subtask_id,
        step_num,
        result.passed,
        project_root=project_path,
        already_verified=True,
    )

    # Emit logs
    _emit_verification_logs(task_id, step_num, step_desc, step, result, project_id)

    # Emit progress
    status = "passed" if result.passed else "failed"
    emit_progress(
        task_id, subtask_id=subtask_id, step=step_num, status=status, project_id=project_id
    )

    return {
        "step_number": step_num,
        "passed": result.passed,
        "output": result.output[:500],
        "reason": result.reason,
        "returncode": result.returncode,
    }


def _emit_verification_logs(
    task_id: str,
    step_num: int,
    step_desc: str,
    step: dict[str, Any],
    result: VerificationResult,
    project_id: str,
) -> None:
    """Emit detailed verification logs for a step."""
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
        task_id,
        "debug",
        f"  cmd: {verify_cmd}",
        source="verify",
        project_id=project_id,
        visibility="internal",
    )

    emit_log(
        task_id,
        "debug" if result.passed else "warn",
        f"  output: {output_preview}",
        source="verify",
        project_id=project_id,
    )

    if not result.passed and result.reason:
        emit_log(
            task_id,
            "warn",
            f"  reason: {result.reason}",
            source="verify",
            project_id=project_id,
        )
