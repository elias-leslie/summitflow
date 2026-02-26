"""AI Review task using Agent Hub complete() with reviewer agent.

Reviews git diffs and routes tasks based on verdict:
- APPROVED: Always auto-merge
- NEEDS_FIX with no concerns: Treat as APPROVED, auto-merge
- NEEDS_FIX with concerns: Create fix subtask and retry
- ESCALATE/unknown: Supervisor triage → approve, fix, or block
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ...logging_config import get_logger
from ...services.agent_hub_client import get_sync_client
from ...storage import log_task_event
from ...storage import tasks as task_store
from ...storage.notifications import create_task_failure_notification
from ...storage.task_spirit import get_task_spirit
from .review_modules.actions import (
    auto_merge,
    create_fix_subtask,
    handle_plan_defect,
)
from .review_modules.diff import get_git_diff
from .review_modules.parsing import parse_review_response
from .review_modules.routing import (
    route_based_on_verdict,
    supervisor_resolve_escalation,
)

logger = get_logger(__name__)


def _notify_failure(project_id: str, task_id: str, task: dict, error_message: str) -> None:
    """Send failure notification, suppressing secondary errors."""
    try:
        session_ids = task_store.get_agent_hub_sessions(task_id)
        create_task_failure_notification(
            project_id=project_id,
            task_id=task_id,
            task_title=task.get("title", "Unknown"),
            error_message=error_message,
            agent_hub_session_ids=session_ids or None,
        )
    except Exception:
        logger.exception("Failed to create notification", task_id=task_id)


def _check_diff_issues(task_id: str, project_id: str, task: dict, git_diff: str) -> dict | None:
    """Return an early-exit result dict if the diff is empty or erroneous, else None."""
    if not git_diff or git_diff.strip() in ("(no changes)", ""):
        logger.warning("Zero-diff detected, rejecting review", task_id=task_id)
        log_task_event(task_id, "Review rejected: no code changes detected", source="review", level="warning")
        task_store.update_task_status(task_id, "failed")
        _notify_failure(project_id, task_id, task, "No code changes detected — task produced zero diff.")
        return {"task_id": task_id, "status": "rejected", "verdict": "REJECTED",
                "message": "No code changes detected — task produced zero diff"}

    if git_diff.strip().startswith("(error"):
        logger.warning("Diff error detected, blocking review", task_id=task_id, diff=git_diff[:200])
        log_task_event(task_id, f"Review blocked: diff extraction failed — {git_diff.strip()[:200]}",
                       source="review", level="error")
        task_store.update_task_status(task_id, "blocked")
        _notify_failure(project_id, task_id, task, f"Diff extraction failed: {git_diff.strip()[:200]}")
        return {"task_id": task_id, "status": "blocked", "verdict": "BLOCKED",
                "message": f"Cannot review: {git_diff.strip()}"}

    return None


def _build_prompt(task: dict, complexity: str, git_diff: str, task_id: str) -> str:
    """Build the reviewer prompt from task metadata and diff."""
    spirit = get_task_spirit(task_id)
    done_when = spirit.get("done_when", []) if spirit else []
    done_when_text = "\n".join(f"- {c}" for c in done_when) if done_when else "(none defined)"
    return (
        f"Task: {task.get('title', '')}\nComplexity: {complexity}\n\n"
        f"Success Criteria (done_when):\n{done_when_text}\n\n"
        f"Git Diff:\n```\n{git_diff[:50000]}\n```\n\n"
        "If done_when criteria are defined, verify the diff addresses each one."
    )


def ai_review(
    task_id: str,
    project_id: str,
    dispatch: Callable[[str, str, str], None] | None = None,
) -> dict[str, Any]:
    """Run AI review on completed task using reviewer agent (Opus).

    Reviews the git diff and provides approval/rejection verdict.
    """
    logger.info("Starting AI review", task_id=task_id, project_id=project_id)

    task = task_store.get_task(task_id)
    if not task:
        return {"task_id": task_id, "status": "error", "message": "Task not found"}

    task_store.update_task_status(task_id, "ai_reviewing")
    git_diff = get_git_diff(task_id, project_id)

    early = _check_diff_issues(task_id, project_id, task, git_diff)
    if early:
        return early

    complexity = task.get("complexity") or "STANDARD"
    prompt = _build_prompt(task, complexity, git_diff, task_id)

    try:
        client = get_sync_client()
        response = client.complete(
            messages=[{"role": "user", "content": prompt}],
            project_id=project_id,
            agent_slug="reviewer",
        )
        review_result = parse_review_response(response.content)
        route_based_on_verdict(task_id, complexity, review_result)
        return {"task_id": task_id, "status": "reviewed",
                "verdict": review_result.get("verdict"), "complexity": complexity}
    except Exception as e:
        logger.warning("AI review failed", task_id=task_id, error=str(e))
        task_store.update_task_status(task_id, "blocked")
        _notify_failure(project_id, task_id, task, f"AI review failed: {e}")
        return {"task_id": task_id, "status": "error", "message": str(e)}


# Backward compatibility: expose private functions for tests
_auto_merge = auto_merge
_create_fix_subtask = create_fix_subtask
_get_git_diff = get_git_diff
_handle_plan_defect = handle_plan_defect
_parse_review_response = parse_review_response
_route_based_on_verdict = route_based_on_verdict
_supervisor_resolve_escalation = supervisor_resolve_escalation

__all__ = [
    "_auto_merge",
    "_create_fix_subtask",
    "_get_git_diff",
    "_handle_plan_defect",
    "_parse_review_response",
    "_route_based_on_verdict",
    "_supervisor_resolve_escalation",
    "ai_review",
]
