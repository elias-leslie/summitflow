"""Celery tasks for autonomous system maintenance and cleanup.

Includes:
- Task claim expiration handling
- Worktree cleanup for completed/cancelled tasks
- Merge and cleanup for approved SIMPLE tasks
"""

from __future__ import annotations

import logging
import subprocess
from typing import Any

from app.celery_app import celery_app
from app.services.worktree import get_task_worktree, remove_task_worktree
from app.storage import tasks as task_store
from app.storage.projects import get_project_root_path

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


@celery_app.task(name="summitflow.merge_and_cleanup_task_worktree")
def merge_and_cleanup_task_worktree(
    task_id: str,
    project_id: str,
) -> dict[str, Any]:
    """Merge task branch to main and clean up worktree.

    Used for auto-approved SIMPLE tasks. Performs:
    1. Get task worktree info
    2. Switch to base branch in main repo
    3. Merge task branch with --no-ff
    4. Remove worktree
    5. Delete task branch

    Args:
        task_id: Task ID to merge and clean up
        project_id: Project ID for worktree lookup

    Returns:
        Dict with merge/cleanup result
    """
    try:
        worktree = get_task_worktree(task_id, project_id)
        if not worktree:
            return {
                "task_id": task_id,
                "status": "skipped",
                "reason": "no_worktree",
            }

        task_branch = worktree.branch
        base_branch = worktree.base_branch or "main"
        project_root = get_project_root_path(project_id)

        if not project_root:
            return {
                "task_id": task_id,
                "status": "error",
                "error": f"No root path for project {project_id}",
            }

        # Step 1: Checkout base branch in main repo
        checkout_result = subprocess.run(
            ["git", "checkout", base_branch],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if checkout_result.returncode != 0:
            return {
                "task_id": task_id,
                "status": "error",
                "error": f"Failed to checkout {base_branch}: {checkout_result.stderr}",
            }

        # Step 2: Merge task branch
        merge_result = subprocess.run(
            ["git", "merge", "--no-ff", task_branch, "-m", f"Merge task {task_id}"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if merge_result.returncode != 0:
            return {
                "task_id": task_id,
                "status": "error",
                "error": f"Failed to merge {task_branch}: {merge_result.stderr}",
            }

        logger.info(f"Merged {task_branch} into {base_branch}", extra={"task_id": task_id})

        # Step 3: Remove worktree (don't delete branch yet - still need it for branch deletion)
        remove_task_worktree(task_id, delete_branch=False, project_id=project_id)

        # Step 4: Delete the task branch
        delete_result = subprocess.run(
            ["git", "branch", "-d", task_branch],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=30,
        )
        branch_deleted = delete_result.returncode == 0
        if not branch_deleted:
            logger.warning(
                f"Failed to delete branch {task_branch}: {delete_result.stderr}",
                extra={"task_id": task_id},
            )

        return {
            "task_id": task_id,
            "status": "merged",
            "task_branch": task_branch,
            "base_branch": base_branch,
            "branch_deleted": branch_deleted,
        }

    except subprocess.TimeoutExpired:
        logger.error(f"Timeout during merge/cleanup for task {task_id}")
        return {
            "task_id": task_id,
            "status": "error",
            "error": "Git operation timed out",
        }
    except Exception as e:
        logger.error(f"Error merging/cleaning up task {task_id}: {e}")
        return {
            "task_id": task_id,
            "status": "error",
            "error": str(e),
        }
