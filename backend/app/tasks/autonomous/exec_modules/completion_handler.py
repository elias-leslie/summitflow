"""Task completion and quality gate handling."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ....logging_config import get_logger
from ....storage import tasks as task_store
from .completion_status import (
    build_early_completion_verification,
    build_partial_completion_verification,
    build_successful_completion_verification,
    handle_status_transition_error,
    transition_to_review_or_complete,
)
from .events import emit_error, emit_log
from .followup_tasks import create_followup_task_for_failures
from .quality_gate import run_quality_gate_with_autofix

logger = get_logger(__name__)


def handle_early_completion(
    task_id: str,
    project_id: str,
    total_subtasks: int,
    dispatch: Callable[[str, str, str], None] | None = None,
) -> dict[str, Any]:
    """Handle case where all subtasks are already complete.

    Args:
        task_id: The task ID
        project_id: The project ID
        total_subtasks: Total number of subtasks
        dispatch: Optional callback to trigger downstream workflows

    Returns:
        Result dict with status ai_reviewing or completed
    """
    try:
        verification_result = build_early_completion_verification(total_subtasks)
        task_store.update_task(task_id, verification_result=verification_result)

        final_status = transition_to_review_or_complete(
            task_id,
            project_id,
            "All subtasks already complete",
            dispatch,
        )

        return {
            "task_id": task_id,
            "status": final_status,
            "message": "Triggered QA review for complete subtasks"
            if final_status == "ai_reviewing"
            else "Completed without review",
        }
    except Exception as e:
        emit_log(
            task_id,
            "error",
            f"Failed to transition status: {e}",
            project_id=project_id,
        )
        task_store.update_task_status(task_id, "blocked")
        return {
            "task_id": task_id,
            "status": "blocked",
            "message": f"Status transition failed: {e}",
        }


def handle_successful_completion(
    task_id: str,
    project_id: str,
    project_path: str,
    results: list[dict[str, Any]],
    dispatch: Callable[[str, str, str], None] | None = None,
) -> bool:
    """Handle successful task completion with quality gate.

    Args:
        task_id: The task ID
        project_id: The project ID
        project_path: Path to project directory
        results: List of subtask execution results
        dispatch: Optional callback to trigger downstream workflows

    Returns:
        True if completed successfully, False if blocked
    """
    final_gate_passed = run_quality_gate_with_autofix(task_id, project_path, project_id)

    if not final_gate_passed:
        task_store.update_task_status(task_id, "blocked")
        emit_error(
            task_id,
            "Final quality gate failed after auto-fix attempt",
            project_id=project_id,
        )
        return False

    try:
        verification_result = build_successful_completion_verification(results)
        task_store.update_task(task_id, verification_result=verification_result)

        execution_clean = verification_result["execution_clean"]
        log_message = f"All subtasks passed + quality gate passed (clean={execution_clean})"

        transition_to_review_or_complete(task_id, project_id, log_message, dispatch)
        return True
    except Exception as e:
        handle_status_transition_error(task_id, project_id, e, {"Results": results})
        return False


def handle_partial_completion(
    task_id: str,
    project_id: str,
    project_path: str,
    results: list[dict[str, Any]],
    dispatch: Callable[[str, str, str], None] | None = None,
) -> bool:
    """Handle case where some subtasks passed but others failed.

    Args:
        task_id: The task ID
        project_id: The project ID
        project_path: Path to project directory
        results: List of subtask execution results
        dispatch: Optional callback to trigger downstream workflows

    Returns:
        True if partial merge was set up, False if skipped
    """
    passed = [r for r in results if r.get("status") == "passed"]
    failed = [r for r in results if r.get("status") != "passed"]

    if not passed or not failed:
        return False

    emit_log(
        task_id,
        "info",
        f"Partial completion: {len(passed)}/{len(results)} subtasks passed. "
        f"Proceeding with partial merge.",
        project_id=project_id,
    )

    create_followup_task_for_failures(task_id, project_id, failed)

    try:
        verification_result = build_partial_completion_verification(results, passed, failed)
        task_store.update_task(task_id, verification_result=verification_result)

        transition_to_review_or_complete(
            task_id,
            project_id,
            "Partial merge completed",
            dispatch,
        )
        return True
    except Exception as e:
        emit_log(
            task_id,
            "error",
            f"Failed to set up partial merge: {e}",
            project_id=project_id,
        )
        task_store.update_task_status(task_id, "blocked")
        return False


def handle_failed_execution(task_id: str, project_id: str) -> None:
    """Handle case where subtasks failed.

    Args:
        task_id: The task ID
        project_id: The project ID
    """
    try:
        task_store.update_task_status(task_id, "blocked")
        emit_log(
            task_id,
            "info",
            "Execution paused - subtask verification failed",
            project_id=project_id,
        )
    except Exception as e:
        emit_log(
            task_id,
            "error",
            f"Failed to set blocked status: {type(e).__name__}: {e!s}",
            project_id=project_id,
        )