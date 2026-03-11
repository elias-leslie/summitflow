"""Worktree cleanup operations for completed/cancelled tasks."""

from __future__ import annotations

import logging
from typing import Literal, TypedDict

from app.services.worktree import get_task_worktree, remove_task_worktree
from cli.commands.cleanup_git import has_uncommitted_changes

logger = logging.getLogger(__name__)


class WorktreeCleanupSuccess(TypedDict):
    """Successful worktree cleanup result."""

    task_id: str
    status: Literal["cleaned"]
    worktree_path: str
    branch: str
    branch_deleted: bool


class WorktreeCleanupSkipped(TypedDict):
    """Skipped worktree cleanup result."""

    task_id: str
    status: Literal["skipped"]
    reason: str


class WorktreeCleanupFailed(TypedDict):
    """Failed worktree cleanup result."""

    task_id: str
    status: Literal["failed", "error"]
    reason: str | None
    error: str | None


WorktreeCleanupResult = (
    WorktreeCleanupSuccess | WorktreeCleanupSkipped | WorktreeCleanupFailed
)


def cleanup_task_worktree(
    task_id: str,
    delete_branch: bool = False,
    project_id: str | None = None,
) -> WorktreeCleanupResult:
    """Clean up worktree for a completed or cancelled task.

    Called when a task reaches a terminal state (completed, cancelled, failed).
    Removes the worktree directory but preserves the branch by default
    (branch can be merged via PR or deleted manually).

    Args:
        task_id: Task ID whose worktree should be cleaned up
        delete_branch: Whether to also delete the task branch (default: False)

    Returns:
        Dict with cleanup result
    """
    try:
        worktree = get_task_worktree(task_id, project_id)
        if not worktree:
            return {
                "task_id": task_id,
                "status": "skipped",
                "reason": "no_worktree",
            }

        if has_uncommitted_changes(str(worktree.path)):
            return {
                "task_id": task_id,
                "status": "skipped",
                "reason": "dirty_worktree",
            }

        worktree_path = str(worktree.path)
        branch = worktree.branch

        removed = remove_task_worktree(
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
            "Cleaned up worktree for task %s",
            task_id,
            extra={
                "task_id": task_id,
                "worktree_path": worktree_path,
                "branch": branch,
                "branch_deleted": delete_branch,
            },
        )
        return {
            "task_id": task_id,
            "status": "cleaned",
            "worktree_path": worktree_path,
            "branch": branch,
            "branch_deleted": delete_branch,
        }

    except Exception as e:
        logger.error("Error cleaning up worktree for task %s: %s", task_id, e)
        return {
            "task_id": task_id,
            "status": "error",
            "reason": None,
            "error": str(e),
        }
