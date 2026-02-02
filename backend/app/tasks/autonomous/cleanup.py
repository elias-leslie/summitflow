"""Celery tasks for autonomous system maintenance and cleanup.

Includes:
- Task claim expiration handling
- Worktree cleanup for completed/cancelled tasks
"""

from __future__ import annotations

import logging
from typing import Any

from app.celery_app import celery_app
from app.services.worktree import get_task_worktree, remove_task_worktree
from app.storage import tasks as task_store

logger = logging.getLogger(__name__)


@celery_app.task(name="summitflow.reset_expired_task_claims")
def reset_expired_task_claims() -> dict[str, int | str]:
    """Reset tasks with expired claim locks.

    Finds tasks where:
    - status is 'running'
    - lock_expires_at has passed
    - claimed_by is set

    Resets them to 'pending' with cleared claim fields.

    Returns:
        Dict with reset_count
    """
    try:
        count = task_store.reset_expired_claims()
        if count > 0:
            logger.info(f"Reset {count} expired task claims")
        return {"reset_count": count}
    except Exception as e:
        logger.error(f"Error resetting expired claims: {e}")
        return {"error": str(e), "reset_count": 0}


@celery_app.task(name="summitflow.cleanup_task_worktree")
def cleanup_task_worktree(
    task_id: str,
    delete_branch: bool = False,
) -> dict[str, Any]:
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
        worktree = get_task_worktree(task_id)
        if not worktree:
            return {
                "task_id": task_id,
                "status": "skipped",
                "reason": "no_worktree",
            }

        worktree_path = str(worktree.path)
        branch = worktree.branch

        removed = remove_task_worktree(task_id, delete_branch=delete_branch)

        if removed:
            logger.info(
                f"Cleaned up worktree for task {task_id}",
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
        else:
            return {
                "task_id": task_id,
                "status": "failed",
                "reason": "removal_failed",
            }

    except Exception as e:
        logger.error(f"Error cleaning up worktree for task {task_id}: {e}")
        return {
            "task_id": task_id,
            "status": "error",
            "error": str(e),
        }
