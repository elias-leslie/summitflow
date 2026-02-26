"""Result processing and final status determination."""

from __future__ import annotations

from typing import Any

from ....core.debug import debug_error, debug_success
from ....logging_config import get_logger
from ....storage.subtasks import update_subtask_passes
from .events import emit_log
from .memory_writes import save_subtask_learning
from .session import extract_handoff_summary
from .steps import compute_issue_id

logger = get_logger(__name__)


def _handle_passed_result(
    task_id: str,
    subtask_id: str,
    subtask_short_id: str,
    project_id: str,
    response_content: str,
    duration: float,
    total_attempts: int,
    self_fix_attempts: int,
    supervisor_guided_attempts: int,
) -> None:
    """Handle logging and side-effects when all checks passed."""
    duration_str = f"{duration:.1f}s"
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


def _handle_failed_result(
    task_id: str,
    subtask_short_id: str,
    project_id: str,
    step_results: list[dict[str, Any]],
    duration: float,
    total_attempts: int,
    self_fix_attempts: int,
    supervisor_guided_attempts: int,
    issue_counts: dict[str, int],
) -> None:
    """Handle logging and issue counting when some checks failed."""
    duration_str = f"{duration:.1f}s"
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


def _save_learning_and_build_result(
    task_id: str,
    subtask_short_id: str,
    subtask_type: str | None,
    project_id: str,
    all_passed: bool,
    step_results: list[dict[str, Any]],
    issue_counts: dict[str, int],
    self_fix_attempts: int,
    supervisor_guided_attempts: int,
    extensions_granted: int,
) -> dict[str, Any]:
    """Save subtask learning and build the final result dictionary."""
    save_subtask_learning(
        task_id,
        subtask_short_id,
        subtask_type,
        project_id,
        all_passed,
        self_fix_attempts,
        supervisor_guided_attempts,
        step_results,
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
    subtask_type: str | None = None,
) -> dict[str, Any]:
    """Process final result after retry loop completes.

    Returns:
        Result dictionary with status, step_results, and metrics
    """
    total_attempts = 1 + self_fix_attempts + supervisor_guided_attempts
    if all_passed:
        _handle_passed_result(
            task_id, subtask_id, subtask_short_id, project_id,
            response_content, duration, total_attempts,
            self_fix_attempts, supervisor_guided_attempts,
        )
    else:
        _handle_failed_result(
            task_id, subtask_short_id, project_id, step_results,
            duration, total_attempts, self_fix_attempts,
            supervisor_guided_attempts, issue_counts,
        )
    return _save_learning_and_build_result(
        task_id, subtask_short_id, subtask_type, project_id,
        all_passed, step_results, issue_counts,
        self_fix_attempts, supervisor_guided_attempts, extensions_granted,
    )
