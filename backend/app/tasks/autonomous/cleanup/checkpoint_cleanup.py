"""Checkpoint cleanup operations for completed or cancelled tasks."""

from __future__ import annotations

from typing import Literal, TypedDict

from app.services.task_checkout import get_task_checkout, remove_task_checkout
from app.utils._git_core import has_uncommitted_changes

from ....logging_config import get_logger

logger = get_logger(__name__)


class CheckpointCleanupSuccess(TypedDict):
    """Successful checkpoint cleanup result."""

    task_id: str
    status: Literal["cleaned"]
    checkout_path: str
    branch: str
    branch_deleted: bool


class CheckpointCleanupSkipped(TypedDict):
    """Skipped checkpoint cleanup result."""

    task_id: str
    status: Literal["skipped"]
    reason: str


class CheckpointCleanupFailed(TypedDict):
    """Failed checkpoint cleanup result."""

    task_id: str
    status: Literal["failed", "error"]
    reason: str | None
    error: str | None


CheckpointCleanupResult = (
    CheckpointCleanupSuccess | CheckpointCleanupSkipped | CheckpointCleanupFailed
)


def cleanup_task_checkpoint(
    task_id: str,
    delete_branch: bool = False,
    project_id: str | None = None,
) -> CheckpointCleanupResult:
    """Clean up checkpoint state for a completed or cancelled task.

    Called when a task reaches a terminal state (completed, cancelled, failed).
    Removes checkpoint metadata and preserves the branch by default.

    Args:
        task_id: Task ID whose checkpoint should be cleaned up
        delete_branch: Whether to also delete the task branch (default: False)

    Returns:
        Dict with cleanup result
    """
    try:
        checkout = get_task_checkout(task_id, project_id)
        if not checkout:
            return {
                "task_id": task_id,
                "status": "skipped",
                "reason": "no_checkpoint",
            }

        if has_uncommitted_changes(checkout.path):
            return {
                "task_id": task_id,
                "status": "skipped",
                "reason": "dirty_checkout",
            }

        checkout_path = str(checkout.path)
        branch = checkout.branch

        removed = remove_task_checkout(
            task_id,
            delete_branch=delete_branch,
            project_id=project_id,
        )

        if not removed:
            return {
                "task_id": task_id,
                "status": "failed",
                "reason": "removal_failed",
                "error": None,
            }

        logger.info(
            "Cleaned up checkpoint for task %s",
            task_id,
            extra={
                "task_id": task_id,
                "checkout_path": checkout_path,
                "branch": branch,
                "branch_deleted": delete_branch,
            },
        )
        return {
            "task_id": task_id,
            "status": "cleaned",
            "checkout_path": checkout_path,
            "branch": branch,
            "branch_deleted": delete_branch,
        }

    except Exception as e:
        logger.error("Error cleaning up checkpoint for task %s: %s", task_id, e)
        return {
            "task_id": task_id,
            "status": "error",
            "reason": None,
            "error": str(e),
        }
