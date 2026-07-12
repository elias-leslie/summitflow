"""Status transition and verification result handling for task completion."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ....logging_config import get_logger
from ....storage import tasks as task_store
from ....storage.notifications import (
    create_task_completion_notification,
    create_task_failure_notification,
)
from .events import emit_log

logger = get_logger(__name__)


def _notify_completion(task_id: str, project_id: str) -> None:
    """Send a task completion notification with Johnny's voice."""
    try:
        task = task_store.get_task(task_id)
        task_title = task.get("title", "Unknown") if task else "Unknown"
        session_ids = task_store.get_agent_hub_sessions(task_id)
        create_task_completion_notification(
            project_id=project_id,
            task_id=task_id,
            task_title=task_title,
            agent_hub_session_ids=session_ids or None,
        )
    except Exception:
        logger.exception("Failed to create completion notification", task_id=task_id)


def notify_failure(
    task_id: str,
    project_id: str,
    error_message: str,
    subtask_id: str | None = None,
    blocker_summary: str | None = None,
    recommendation: str | None = None,
) -> None:
    """Send a task failure notification."""
    try:
        task = task_store.get_task(task_id)
        task_title = task.get("title", "Unknown") if task else "Unknown"
        session_ids = task_store.get_agent_hub_sessions(task_id)
        create_task_failure_notification(
            project_id=project_id,
            task_id=task_id,
            task_title=task_title,
            error_message=error_message,
            agent_hub_session_ids=session_ids or None,
            subtask_id=subtask_id,
            blocker_summary=blocker_summary,
            recommendation=recommendation,
        )
    except Exception:
        logger.exception("Failed to create failure notification", task_id=task_id)


def build_early_completion_verification(total_subtasks: int) -> dict[str, Any]:
    """Build verification result for early completion (all subtasks already done)."""
    return {
        "evidence_verified": True,
        "verification_source": "autonomous_preverified_subtasks",
        "execution_clean": True,
        "subtask_count": total_subtasks,
        "total_self_fix_attempts": 0,
        "total_supervisor_attempts": 0,
    }


def build_successful_completion_verification(
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build verification result when all subtasks pass."""
    execution_clean = all(
        r.get("self_fix_attempts", 0) == 0 and r.get("supervisor_guided_attempts", 0) == 0
        for r in results
    )
    total_extensions = sum(r.get("extensions_granted", 0) for r in results)

    result: dict[str, Any] = {
        "evidence_verified": True,
        "verification_source": "autonomous_quality_gate",
        "execution_clean": execution_clean,
        "subtask_count": len(results),
        "total_self_fix_attempts": sum(r.get("self_fix_attempts", 0) for r in results),
        "total_supervisor_attempts": sum(
            r.get("supervisor_guided_attempts", 0) for r in results
        ),
        "total_extensions_granted": total_extensions,
    }
    return result


def _do_complete_transition(task_id: str, project_id: str, log_message: str) -> str:
    """Set task to completed and send a completion notification."""
    from ....tasks.autonomous.cleanup.checkpoint_cleanup import cleanup_task_checkpoint

    task_store.update_task_status(task_id, "completed")
    emit_log(
        task_id,
        "info",
        f"{log_message}, skipping review (require_review=false)",
        project_id=project_id,
    )
    _notify_completion(task_id, project_id)

    cleanup_result = cleanup_task_checkpoint(task_id, delete_branch=False, project_id=project_id)
    if cleanup_result.get("status") != "cleaned":
        reason = str(cleanup_result.get("reason") or cleanup_result.get("error") or "unknown")
        emit_log(
            task_id,
            "warning",
            f"Completed task needs cleanup review: {reason}",
            project_id=project_id,
        )
    return "completed"


def transition_to_complete(
    task_id: str,
    project_id: str,
    log_message: str,
    dispatch: Callable[[str, str, str], None] | None = None,
) -> str:
    """Transition task to a merge-derived terminal state ("completed" or "failed").

    `dispatch` is unused; deterministic quality gates replaced the LLM review tier.
    """
    del dispatch
    return _do_complete_transition(task_id, project_id, log_message)


def handle_status_transition_error(
    task_id: str,
    project_id: str,
    error: Exception,
    context: dict[str, Any] | None = None,
) -> None:
    """Log, block, and notify on a status-transition failure."""
    error_msg = f"Failed to transition status: {type(error).__name__}: {error!s}"
    if context:
        parts = [error_msg, f"Task ID: {task_id}", f"Project ID: {project_id}"]
        parts.extend(f"{key}: {value}" for key, value in context.items())
        error_msg = "\n".join(parts)

    emit_log(task_id, "error", error_msg, project_id=project_id)
    task_store.update_task_status(task_id, "failed")
    emit_log(
        task_id,
        "error",
        "Task set to failed due to status transition failure",
        project_id=project_id,
    )
    notify_failure(task_id, project_id, f"Status transition failed: {error}")
