"""Review verdict handlers for autonomous task validation.

Handles different review outcomes (approve, reject, fix request)
with appropriate task state transitions and git operations.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ...logging_config import get_logger
from ...services.git_service import get_current_branch, push_branch, revert_to
from ...storage import log_task_event
from ...storage import tasks as task_store
from .review_utils import get_project_path

logger = get_logger(__name__)


def handle_approval(
    task: dict[str, Any],
    review_result: dict[str, Any],
    auto_push: bool = False,
    resolved_path: Path | str | None = None,
) -> dict[str, Any]:
    """Handle an approved task.

    Marks the task as completed and optionally pushes to remote.

    Args:
        task: Task dict
        review_result: Review result from opus_review
        auto_push: Whether to push changes to remote
        resolved_path: Path to git repo

    Returns:
        Updated task dict
    """
    resolved_path = get_project_path(task, resolved_path)

    task_id = task.get("id")
    if not task_id:
        raise ValueError("Task must have an id")

    existing_result = task.get("review_result") or {}
    merged_result = {**existing_result, **review_result}
    task_store.update_task(task_id, review_result=merged_result)

    updated = task_store.update_task_status(task_id, "completed")

    logger.info("task_approved", task_id=task_id)

    if auto_push:
        try:
            branch = get_current_branch(resolved_path)
            push_branch(branch, resolved_path)
            logger.info("task_pushed", task_id=task_id, branch=branch)
        except RuntimeError as e:
            logger.warning("task_push_failed", task_id=task_id, error=str(e))

    return updated or task


def handle_rejection(
    task: dict[str, Any],
    review_result: dict[str, Any],
    resolved_path: Path | str | None = None,
) -> dict[str, Any]:
    """Handle a rejected task.

    Reverts changes to pre_merge_sha and marks task for human review.

    Args:
        task: Task dict
        review_result: Review result from opus_review
        resolved_path: Path to git repo

    Returns:
        Updated task dict
    """
    resolved_path = get_project_path(task, resolved_path)

    task_id = task.get("id")
    if not task_id:
        raise ValueError("Task must have an id")

    pre_merge_sha = task.get("pre_merge_sha")
    if pre_merge_sha:
        try:
            revert_to(resolved_path, pre_merge_sha)
            logger.info("task_reverted", task_id=task_id, sha=pre_merge_sha[:8])
        except RuntimeError as e:
            logger.error("task_revert_failed", task_id=task_id, error=str(e))

    existing_result = task.get("review_result") or {}
    merged_result = {**existing_result, **review_result}
    task_store.update_task(task_id, review_result=merged_result)

    current_labels = task.get("labels", []) or []
    if "needs-human-review" not in current_labels:
        current_labels.append("needs-human-review")
        task_store.update_task(task_id, labels=current_labels)

    error_msg = f"Rejected by Opus review: {review_result.get('summary', 'No summary')}"
    updated = task_store.update_task_status(task_id, "failed", error_message=error_msg)

    logger.info("task_rejected", task_id=task_id, summary=review_result.get("summary"))

    return updated or task


def handle_fix_request(
    task: dict[str, Any],
    review_result: dict[str, Any],
) -> dict[str, Any]:
    """Handle a fix request.

    Appends review feedback to task and resets to running for another iteration.

    Args:
        task: Task dict
        review_result: Review result from opus_review

    Returns:
        Updated task dict
    """
    task_id = task.get("id")
    if not task_id:
        raise ValueError("Task must have an id")

    existing_result = task.get("review_result") or {}
    merged_result = {**existing_result, **review_result}
    task_store.update_task(task_id, review_result=merged_result)

    issues = review_result.get("issues", [])
    suggestions = review_result.get("suggestions", [])

    feedback_parts = ["Review requested fixes:"]
    if issues:
        feedback_parts.append(f"Issues: {', '.join(issues)}")
    if suggestions:
        feedback_parts.append(f"Suggestions: {', '.join(suggestions)}")

    feedback = " | ".join(feedback_parts)
    log_task_event(task_id, feedback)

    updated = task_store.update_task_status(task_id, "pending", validate_transition=False)

    logger.info("task_fix_requested", task_id=task_id, issues=len(issues))

    return updated or task
