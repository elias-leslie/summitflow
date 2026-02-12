"""Merge operations and orchestration for autonomous tasks."""

from __future__ import annotations

import logging
import subprocess

from app.services.worktree import get_task_worktree, remove_task_worktree
from app.storage import tasks as task_store
from app.storage.projects import get_project_root_path

from .git_operations import (
    checkout_base_branch,
    delete_task_branch,
    merge_task_branch,
)
from .merge_types import MergeResult
from .validation import auto_rollback, run_post_merge_validation

logger = logging.getLogger(__name__)


def merge_and_cleanup_task_worktree(
    task_id: str,
    project_id: str,
) -> MergeResult:
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
        if is_task_running(task_id):
            return {
                "task_id": task_id,
                "status": "blocked",
                "reason": "task_still_running",
            }

        worktree = get_task_worktree(task_id, project_id)
        if not worktree:
            return {
                "task_id": task_id,
                "status": "skipped",
                "reason": "no_worktree",
            }

        project_root = get_project_root_path(project_id)
        if not project_root:
            return {
                "task_id": task_id,
                "status": "error",
                "error": f"No root path for project {project_id}",
            }

        task_branch = worktree.branch
        base_branch = worktree.base_branch or "main"

        checkout_error = checkout_base_branch(project_root, base_branch)
        if checkout_error:
            return {
                "task_id": task_id,
                "status": "error",
                "error": checkout_error,
            }

        merge_error = merge_task_branch(project_root, task_branch, task_id)
        if merge_error:
            return {
                "task_id": task_id,
                "status": "error",
                "error": merge_error,
            }

        logger.info(
            f"Merged {task_branch} into {base_branch}",
            extra={"task_id": task_id},
        )

        remove_task_worktree(task_id, delete_branch=False, project_id=project_id)

        branch_deleted = delete_task_branch(project_root, task_branch, task_id)

        validation_passed = run_post_merge_validation(
            task_id, project_root, project_id
        )

        if not validation_passed:
            rollback_success = auto_rollback(
                task_id, project_root, project_id, task_branch
            )
            if rollback_success:
                return {
                    "task_id": task_id,
                    "status": "rolled_back",
                    "task_branch": task_branch,
                    "base_branch": base_branch,
                    "reason": "post_merge_validation_failed",
                }

        return {
            "task_id": task_id,
            "status": "merged",
            "task_branch": task_branch,
            "base_branch": base_branch,
            "branch_deleted": branch_deleted,
            "post_merge_valid": validation_passed,
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


def is_task_running(task_id: str) -> bool:
    """Check if task is still running.

    Args:
        task_id: Task ID to check

    Returns:
        True if task is running, False otherwise
    """
    task = task_store.get_task(task_id)
    if task and task.get("status") == "running":
        logger.warning(
            "merge_blocked_task_running",
            extra={"task_id": task_id},
        )
        return True
    return False


# Re-export internal functions for backward compatibility
_auto_rollback = auto_rollback
_run_post_merge_validation = run_post_merge_validation
