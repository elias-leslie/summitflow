"""Status transition and verification result handling for task completion."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ....logging_config import get_logger
from ....storage import agent_configs
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


def build_early_completion_verification(total_subtasks: int) -> dict[str, Any]:
    """Build verification result for early completion case.

    Args:
        total_subtasks: Total number of subtasks

    Returns:
        Verification result dict
    """
    return {
        "execution_clean": True,
        "subtask_count": total_subtasks,
        "total_self_fix_attempts": 0,
        "total_supervisor_attempts": 0,
    }


def build_successful_completion_verification(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Build verification result for successful completion.

    Args:
        results: List of subtask execution results

    Returns:
        Verification result dict
    """
    execution_clean = all(
        r.get("self_fix_attempts", 0) == 0 and r.get("supervisor_guided_attempts", 0) == 0
        for r in results
    )
    total_extensions = sum(r.get("extensions_granted", 0) for r in results)

    return {
        "execution_clean": execution_clean,
        "subtask_count": len(results),
        "total_self_fix_attempts": sum(r.get("self_fix_attempts", 0) for r in results),
        "total_supervisor_attempts": sum(
            r.get("supervisor_guided_attempts", 0) for r in results
        ),
        "total_extensions_granted": total_extensions,
    }


def build_partial_completion_verification(
    results: list[dict[str, Any]],
    passed: list[dict[str, Any]],
    failed: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build verification result for partial completion.

    Args:
        results: All subtask execution results
        passed: Passing subtask results
        failed: Failed subtask results

    Returns:
        Verification result dict
    """
    failed_ids = [r.get("subtask_id", "") for r in failed]

    return {
        "partial_merge": True,
        "subtask_count": len(results),
        "passed_count": len(passed),
        "failed_count": len(failed),
        "failed_subtasks": failed_ids,
        "total_self_fix_attempts": sum(r.get("self_fix_attempts", 0) for r in results),
        "total_supervisor_attempts": sum(
            r.get("supervisor_guided_attempts", 0) for r in results
        ),
    }


def transition_to_review_or_complete(
    task_id: str,
    project_id: str,
    log_message: str,
    dispatch: Callable[[str, str, str], None] | None = None,
) -> str:
    """Transition task to ai_reviewing or completed based on require_review setting.

    Args:
        task_id: The task ID
        project_id: The project ID
        log_message: Base log message (review status will be appended)
        dispatch: Optional callback to trigger downstream workflows

    Returns:
        Final status: "ai_reviewing" or "completed"
    """
    require_review = agent_configs.get_require_review(project_id)

    # Task-level ai_review=False overrides project-level setting (e.g. refactor tasks)
    if require_review:
        task = task_store.get_task(task_id)
        if task and task.get("ai_review") is False:
            require_review = False
            logger.info(
                "Skipping AI review (task ai_review=False)",
                task_id=task_id,
                project_id=project_id,
            )

    if require_review:
        task_store.update_task_status(task_id, "ai_reviewing")
        emit_log(
            task_id,
            "info",
            f"{log_message}, starting QA review",
            project_id=project_id,
        )
        if dispatch:
            dispatch("review", task_id, project_id)
        return "ai_reviewing"
    else:
        task_store.update_task_status(task_id, "completed")
        emit_log(
            task_id,
            "info",
            f"{log_message}, skipping review (require_review=false)",
            project_id=project_id,
        )
        _notify_completion(task_id, project_id)
        return "completed"


def handle_status_transition_error(
    task_id: str,
    project_id: str,
    error: Exception,
    context: dict[str, Any] | None = None,
) -> None:
    """Handle errors during status transitions.

    Args:
        task_id: The task ID
        project_id: The project ID
        error: The exception that occurred
        context: Optional context information for debugging
    """
    error_msg = f"Failed to transition status: {type(error).__name__}: {error!s}"
    if context:
        error_msg += f"\nTask ID: {task_id}\nProject ID: {project_id}"
        for key, value in context.items():
            error_msg += f"\n{key}: {value}"

    emit_log(task_id, "error", error_msg, project_id=project_id)
    task_store.update_task_status(task_id, "blocked")
    emit_log(
        task_id,
        "error",
        "Task set to blocked due to status transition failure",
        project_id=project_id,
    )
    try:
        task = task_store.get_task(task_id)
        task_title = task.get("title", "Unknown") if task else "Unknown"
        session_ids = task_store.get_agent_hub_sessions(task_id)
        create_task_failure_notification(
            project_id=project_id,
            task_id=task_id,
            task_title=task_title,
            error_message=f"Status transition failed: {error}",
            agent_hub_session_ids=session_ids or None,
        )
    except Exception:
        logger.exception("Failed to create failure notification", task_id=task_id)
