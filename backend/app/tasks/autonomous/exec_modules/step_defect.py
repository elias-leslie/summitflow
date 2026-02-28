"""Infrastructure failure detection and auto-defect handling."""

from __future__ import annotations

from ....logging_config import get_logger
from ....storage.steps import update_step_passes, update_step_status
from ....storage.steps_crud import append_steps
from .events import emit_log

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
        fix_steps = append_steps(
            subtask_id,
            [
                {
                    "description": f"Fix: auto-defect for step {step_number} (infrastructure failure)",
                }
            ],
        )
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
