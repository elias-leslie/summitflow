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


def ai_review(
    task_id: str,
    project_id: str,
    dispatch: Callable[[str, str, str], None] | None = None,
) -> dict[str, Any]:
    """Run AI review on completed task using reviewer agent (Opus).

    Reviews the git diff and provides approval/rejection verdict.

    Args:
        task_id: The task ID to review
        project_id: The project ID
        dispatch: Optional dispatch function (unused, for compatibility)

    Returns:
        Review result with verdict and routing
    """
    logger.info("Starting AI review", task_id=task_id, project_id=project_id)

    task = task_store.get_task(task_id)
    if not task:
        return {"task_id": task_id, "status": "error", "message": "Task not found"}

    task_store.update_task_status(task_id, "ai_reviewing")

    git_diff = get_git_diff(task_id, project_id)

    if not git_diff or git_diff.strip() in ("(no changes)", ""):
        logger.warning("Zero-diff detected, rejecting review", task_id=task_id)
        log_task_event(
            task_id,
            "Review rejected: no code changes detected",
            source="review",
            level="warning",
        )
        task_store.update_task_status(task_id, "failed")
        return {
            "task_id": task_id,
            "status": "rejected",
            "verdict": "REJECTED",
            "message": "No code changes detected — task produced zero diff",
        }

    complexity = task.get("complexity") or "STANDARD"

    prompt = f"""Task: {task.get("title", "")}
Complexity: {complexity}

Git Diff:
```
{git_diff[:5000]}
```"""

    try:
        client = get_sync_client()
        response = client.complete(
            messages=[{"role": "user", "content": prompt}],
            project_id=project_id,
            agent_slug="reviewer",
        )

        review_result = parse_review_response(response.content)
        route_based_on_verdict(task_id, complexity, review_result)

        return {
            "task_id": task_id,
            "status": "reviewed",
            "verdict": review_result.get("verdict"),
            "complexity": complexity,
        }

    except Exception as e:
        logger.warning("AI review failed", task_id=task_id, error=str(e))
        task_store.update_task_status(task_id, "blocked")
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
