"""Task completion and quality gate handling."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ....storage import tasks as task_store
from .ah_events import emit_task_transition
from .completion_status import (
    build_early_completion_verification,
    build_partial_completion_verification,
    build_successful_completion_verification,
    handle_status_transition_error,
    notify_failure,
    transition_to_review_or_complete,
    wake_persona,
)
from .diff_gate import check_diff_gate
from .events import emit_error, emit_log
from .followup_tasks import create_followup_task_for_failures
from .quality_gate import run_quality_gate
from .runtime_evaluator import run_runtime_evaluator


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
        final_status = transition_to_review_or_complete(
            task_id, project_id, "All subtasks already complete", dispatch,
        )
        return {
            "task_id": task_id,
            "status": final_status,
            "message": "Queued AI review for complete subtasks"
            if final_status == "running"
            else "Completed without review",
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
    """Handle successful task completion with diff gate + quality gate + runtime verification."""
    # Diff gate: block completion if no meaningful changes
    diff_result = check_diff_gate(project_path)
    if not diff_result.passed:
        task_store.update_task_status(task_id, "failed")
        emit_task_transition(task_id, "failed", f"Diff gate failed: {diff_result.summary}")
        emit_error(task_id, f"Diff gate blocked completion: {diff_result.summary}", project_id=project_id)
        notify_failure(task_id, project_id, f"No code changes detected: {diff_result.summary}")
        wake_persona(task_id, project_id, "diff_gate_failed",
                     f"Task {task_id} blocked by diff gate — zero meaningful changes vs base branch.")
        return False

    if not run_quality_gate(task_id, project_path, project_id):
        task_store.update_task_status(task_id, "failed")
        emit_task_transition(task_id, "failed", "Quality gate failed")
        emit_error(task_id, "Final quality gate failed", project_id=project_id)
        notify_failure(task_id, project_id, "Quality gate failed.")
        wake_persona(task_id, project_id, "quality_gate",
                     f"Task {task_id} quality gate failed. Investigate and advise.")
        return False

    runtime_result = run_runtime_evaluator(task_id, project_id)
    if runtime_result.mode != "code_only" and not runtime_result.passed:
        task_store.update_task_status(task_id, "failed")
        summary = runtime_result.summary or "Runtime evaluation failed"
        emit_error(task_id, f"Runtime evaluation failed: {summary}", project_id=project_id)
        notify_failure(task_id, project_id, f"Runtime evaluation failed: {summary}")
        wake_persona(
            task_id,
            project_id,
            "runtime_eval_failed",
            f"Task {task_id} runtime evaluation failed: {summary}. Review contract and runtime evidence.",
        )
        return False

    try:
        verification_result = build_successful_completion_verification(results)
        task_store.update_task(task_id, verification_result=verification_result)
        execution_clean = verification_result["execution_clean"]
        log_message = f"All subtasks passed + quality gate passed (clean={execution_clean})"
        transition_to_review_or_complete(task_id, project_id, log_message, dispatch)
        wake_persona(task_id, project_id, "autocode_complete",
                     f"Task {task_id} completed successfully — all subtasks passed + quality gate passed.")
        return True
    except Exception as e:
        handle_status_transition_error(task_id, project_id, e, {"Results": results})
        return False


def _handle_partial_merge_error(
    task_id: str, project_id: str, error: Exception
) -> None:
    """Handle errors when setting up partial merge."""
    emit_log(task_id, "error", f"Failed to set up partial merge: {error}", project_id=project_id)
    task_store.update_task_status(task_id, "failed")
    notify_failure(task_id, project_id, f"Partial merge failed: {error}")


def handle_partial_completion(
    task_id: str,
    project_id: str,
    project_path: str,
    results: list[dict[str, Any]],
    dispatch: Callable[[str, str, str], None] | None = None,
) -> bool:
    """Handle case where some subtasks passed but others failed."""
    passed = [r for r in results if r.get("status") == "passed"]
    failed = [r for r in results if r.get("status") != "passed"]

    if not passed or not failed:
        return False

    emit_log(
        task_id, "info",
        f"Partial completion: {len(passed)}/{len(results)} subtasks passed. "
        "Proceeding with partial merge.",
        project_id=project_id,
    )
    create_followup_task_for_failures(task_id, project_id, failed)

    try:
        verification_result = build_partial_completion_verification(results, passed, failed)
        task_store.update_task(task_id, verification_result=verification_result)
        transition_to_review_or_complete(task_id, project_id, "Partial merge completed", dispatch)
        return True
    except Exception as e:
        _handle_partial_merge_error(task_id, project_id, e)
        return False


def handle_failed_execution(
    task_id: str,
    project_id: str,
    results: list[dict[str, Any]] | None = None,
) -> None:
    """Handle case where subtasks failed."""
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
        wake_persona(task_id, project_id, "task_failure",
                     f"Task {task_id} failed — all subtasks failed verification. "
                     f"Blocker: {blocker_summary or 'unknown'}. Investigate and advise.")
    except Exception as e:
        emit_log(task_id, "error", f"Failed to set blocked status: {type(e).__name__}: {e!s}",
                 project_id=project_id)
