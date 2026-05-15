"""Task completion and quality gate handling."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ....storage import tasks as task_store
from .ah_events import emit_task_transition
from .completion_status import (
    build_early_completion_verification,
    build_successful_completion_verification,
    handle_status_transition_error,
    notify_failure,
    transition_to_complete,
)
from .diff_gate import check_diff_gate
from .events import emit_error, emit_log
from .quality_gate import run_quality_gate

_TERMINAL_TASK_STATUSES = {"completed", "failed", "cancelled", "abandoned", "closed"}


def handle_early_completion(
    task_id: str,
    project_id: str,
    total_subtasks: int,
    dispatch: Callable[[str, str, str], None] | None = None,
) -> dict[str, Any]:
    """Handle case where all subtasks are already complete."""
    try:
        verification_result = build_early_completion_verification(total_subtasks)
        task_store.update_task(task_id, verification_result=verification_result)
        final_status = transition_to_complete(
            task_id, project_id, "All subtasks already complete", dispatch,
        )
        return {
            "task_id": task_id,
            "status": final_status,
            "message": "Completed",
        }
    except Exception as e:
        emit_log(task_id, "error", f"Failed to transition status: {e}", project_id=project_id)
        task_store.update_task_status(task_id, "failed")
        notify_failure(task_id, project_id, f"Status transition failed: {e}")
        return {"task_id": task_id, "status": "failed", "message": f"Status transition failed: {e}"}


def handle_successful_completion(
    task_id: str,
    project_id: str,
    project_path: str,
    results: list[dict[str, Any]],
    dispatch: Callable[[str, str, str], None] | None = None,
) -> bool:
    """Handle successful task completion with diff and quality checks."""
    # Diff gate: block completion if no meaningful changes
    diff_result = check_diff_gate(project_path)
    if not diff_result.passed:
        task_store.update_task_status(task_id, "failed")
        emit_task_transition(task_id, "failed", f"Diff gate failed: {diff_result.summary}")
        emit_error(task_id, f"Diff gate blocked completion: {diff_result.summary}", project_id=project_id)
        notify_failure(task_id, project_id, f"No code changes detected: {diff_result.summary}")
        return False

    if not run_quality_gate(task_id, project_path, project_id):
        task_store.update_task_status(task_id, "failed")
        emit_task_transition(task_id, "failed", "Quality gate failed")
        emit_error(task_id, "Final quality gate failed", project_id=project_id)
        notify_failure(task_id, project_id, "Quality gate failed.")
        return False

    try:
        verification_result = build_successful_completion_verification(results)
        task_store.update_task(task_id, verification_result=verification_result)
        execution_clean = verification_result["execution_clean"]
        log_message = f"All subtasks passed + quality gate passed (clean={execution_clean})"
        transition_to_complete(task_id, project_id, log_message, dispatch)
        return True
    except Exception as e:
        handle_status_transition_error(task_id, project_id, e, {"Results": results})
        return False


def handle_failed_execution(
    task_id: str,
    project_id: str,
    results: list[dict[str, Any]] | None = None,
) -> None:
    """Handle case where subtasks failed."""
    task = task_store.get_task(task_id) or {}
    current_status = str(task.get("status") or "").strip().lower()
    if current_status in _TERMINAL_TASK_STATUSES:
        emit_log(
            task_id,
            "warn",
            f"Execution failure arrived after terminal status {current_status}; leaving task unchanged",
            project_id=project_id,
        )
        return

    subtask_id: str | None = None
    blocker_summary: str | None = None
    if results:
        for r in results:
            if r.get("status") != "passed":
                subtask_id = r.get("subtask_id")
                blocker_summary = r.get("error") or r.get("message")
                break

    try:
        task_store.update_task_status(task_id, "failed")
        emit_task_transition(task_id, "failed", f"All subtasks failed: {blocker_summary or 'unknown'}")
        emit_log(task_id, "info", "Execution paused - subtask verification failed", project_id=project_id)
        notify_failure(task_id, project_id, "All subtasks failed verification.",
                       subtask_id=subtask_id, blocker_summary=blocker_summary)
    except ValueError as e:
        task = task_store.get_task(task_id) or {}
        current_status = str(task.get("status") or "").strip().lower()
        if current_status in _TERMINAL_TASK_STATUSES:
            emit_log(
                task_id,
                "warn",
                f"Execution failure raced terminal status {current_status}; leaving task unchanged",
                project_id=project_id,
            )
            return
        emit_log(task_id, "error", f"Failed to set blocked status: {type(e).__name__}: {e!s}",
                 project_id=project_id)
    except Exception as e:
        emit_log(task_id, "error", f"Failed to set blocked status: {type(e).__name__}: {e!s}",
                 project_id=project_id)
