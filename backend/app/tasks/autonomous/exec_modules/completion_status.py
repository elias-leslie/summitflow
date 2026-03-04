"""Status transition and verification result handling for task completion."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx

from ....logging_config import get_logger
from ....services._agent_hub_config import (
    AGENT_HUB_URL,
    SUMMITFLOW_CLIENT_ID,
    SUMMITFLOW_REQUEST_SOURCE,
)
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


def wake_persona(task_id: str, project_id: str, event_type: str, context: str) -> None:
    """Fire-and-forget wake to persona agent via Agent Hub. Non-blocking."""
    try:
        headers = {
            "X-Client-Id": SUMMITFLOW_CLIENT_ID or "",
            "X-Request-Source": SUMMITFLOW_REQUEST_SOURCE,
        }
        with httpx.Client(timeout=5.0) as client:
            client.post(
                f"{AGENT_HUB_URL}/api/wake",
                json={
                    "agent_slug": "persona",
                    "context": context,
                    "project_id": project_id,
                    "event_type": event_type,
                    "task_id": task_id,
                },
                headers=headers,
            )
    except Exception:
        logger.debug("Persona wake failed (non-critical)", task_id=task_id)


def build_early_completion_verification(total_subtasks: int) -> dict[str, Any]:
    """Build verification result for early completion (all subtasks already done)."""
    return {
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
        "execution_clean": execution_clean,
        "subtask_count": len(results),
        "total_self_fix_attempts": sum(r.get("self_fix_attempts", 0) for r in results),
        "total_supervisor_attempts": sum(
            r.get("supervisor_guided_attempts", 0) for r in results
        ),
        "total_extensions_granted": total_extensions,
    }
    return result


def build_partial_completion_verification(
    results: list[dict[str, Any]],
    passed: list[dict[str, Any]],
    failed: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build verification result when only some subtasks pass (partial merge)."""
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


def _resolve_require_review(task_id: str, project_id: str) -> bool:
    """Resolve whether AI review is required, respecting task-level overrides.

    Task-level ai_review=False overrides the project-level require_review setting.
    """
    require_review = agent_configs.get_require_review(project_id)
    if not require_review:
        return False
    task = task_store.get_task(task_id)
    if task and task.get("ai_review") is False:
        logger.info(
            "Skipping AI review (task ai_review=False)",
            task_id=task_id,
            project_id=project_id,
        )
        return False
    return True


def _do_review_transition(
    task_id: str,
    project_id: str,
    log_message: str,
    dispatch: Callable[[str, str, str], None] | None,
) -> str:
    """Set task to ai_reviewing and optionally dispatch the review workflow."""
    task_store.update_task_status(task_id, "ai_reviewing")
    emit_log(task_id, "info", f"{log_message}, starting QA review", project_id=project_id)
    if dispatch:
        dispatch("review", task_id, project_id)
    return "ai_reviewing"


def _do_complete_transition(task_id: str, project_id: str, log_message: str) -> str:
    """Set task to completed and send a completion notification."""
    task_store.update_task_status(task_id, "completed")
    emit_log(
        task_id,
        "info",
        f"{log_message}, skipping review (require_review=false)",
        project_id=project_id,
    )
    _notify_completion(task_id, project_id)
    return "completed"


def transition_to_review_or_complete(
    task_id: str,
    project_id: str,
    log_message: str,
    dispatch: Callable[[str, str, str], None] | None = None,
) -> str:
    """Transition task to ai_reviewing or completed based on require_review setting.

    Returns the final status: "ai_reviewing" or "completed".
    """
    if _resolve_require_review(task_id, project_id):
        return _do_review_transition(task_id, project_id, log_message, dispatch)
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
    notify_failure(task_id, project_id, f"Status transition failed: {error}")
