"""Result processing and final status determination."""

from __future__ import annotations

from typing import Any

from ....core.debug import debug_error, debug_success
from ....logging_config import get_logger
from ....storage.subtasks import update_subtask_passes
from .events import emit_log
from .session import extract_handoff_summary
from .steps import compute_issue_id

logger = get_logger(__name__)


def process_final_result(
    task_id: str,
    subtask_id: str,
    subtask_short_id: str,
    project_id: str,
    all_passed: bool,
    step_results: list[dict[str, Any]],
    response_content: str,
    duration: float,
    self_fix_attempts: int,
    supervisor_guided_attempts: int,
    extensions_granted: int,
    issue_counts: dict[str, int],
) -> dict[str, Any]:
    """Process final result after retry loop completes.

    Returns:
        Result dictionary with status, step_results, and metrics
    """
    duration_str = f"{duration:.1f}s"
    total_attempts = 1 + self_fix_attempts + supervisor_guided_attempts

    if all_passed:
        update_subtask_passes(task_id, subtask_short_id, passes=True)
        extract_handoff_summary(subtask_id, response_content)
        attempt_info = f" (after {total_attempts} attempts)" if total_attempts > 1 else ""
        emit_log(
            task_id,
            "info",
            f"Subtask {subtask_short_id} PASSED{attempt_info} ({duration_str})",
            project_id=project_id,
        )
        debug_success(
            f"Subtask {subtask_short_id} verified",
            task_id=task_id,
            project_id=project_id,
            duration_ms=duration * 1000,
            self_fix_attempts=self_fix_attempts,
            supervisor_guided_attempts=supervisor_guided_attempts,
        )
    else:
        failed_steps = [r for r in step_results if not r["passed"]]
        for fail in failed_steps:
            error_msg = fail.get("error") or fail.get("reason") or "verification failed"
            issue_id = compute_issue_id(error_msg)
            issue_counts[issue_id] = issue_counts.get(issue_id, 0) + 1
        emit_log(
            task_id,
            "warn",
            f"Subtask {subtask_short_id} FAILED after {total_attempts} attempts: "
            f"{len(failed_steps)} step(s) ({duration_str})",
            project_id=project_id,
        )
        debug_error(
            f"Subtask {subtask_short_id} verification failed after self-healing",
            task_id=task_id,
            project_id=project_id,
            failed_steps=len(failed_steps),
            duration_ms=duration * 1000,
            self_fix_attempts=self_fix_attempts,
            supervisor_guided_attempts=supervisor_guided_attempts,
        )

    return {
        "subtask_id": subtask_short_id,
        "status": "passed" if all_passed else "failed",
        "step_results": step_results,
        "issue_counts": {k: v for k, v in issue_counts.items() if v >= 2},
        "self_fix_attempts": self_fix_attempts,
        "supervisor_guided_attempts": supervisor_guided_attempts,
        "extensions_granted": extensions_granted,
    }
