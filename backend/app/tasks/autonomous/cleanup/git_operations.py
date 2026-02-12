"""Low-level git operations for merge and cleanup tasks."""

from __future__ import annotations

import logging
import subprocess

logger = logging.getLogger(__name__)


def checkout_base_branch(project_root: str, base_branch: str) -> str | None:
    """Checkout base branch in main repo.

    Args:
        project_root: Path to project root directory
        base_branch: Name of base branch to checkout

    Returns:
        Error message if checkout failed, None if successful
    """
    result = subprocess.run(
        ["git", "checkout", base_branch],
        cwd=project_root,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        return f"Failed to checkout {base_branch}: {result.stderr}"
    return None


def merge_task_branch(
    project_root: str,
    task_branch: str,
    task_id: str,
) -> str | None:
    """Merge task branch into current branch.

    Args:
        project_root: Path to project root directory
        task_branch: Name of task branch to merge
        task_id: Task ID for commit message

    Returns:
        Error message if merge failed, None if successful
    """
    result = subprocess.run(
        ["git", "merge", "--no-ff", task_branch, "-m", f"Merge task {task_id}"],
        cwd=project_root,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        return f"Failed to merge {task_branch}: {result.stderr}"
    return None


def delete_task_branch(
    project_root: str,
    task_branch: str,
    task_id: str,
) -> bool:
    """Delete task branch after merge.

    Args:
        project_root: Path to project root directory
        task_branch: Name of branch to delete
        task_id: Task ID for logging

    Returns:
        True if branch was deleted, False otherwise
    """
    result = subprocess.run(
        ["git", "branch", "-d", task_branch],
        cwd=project_root,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        logger.warning(
            f"Failed to delete branch {task_branch}: {result.stderr}",
            extra={"task_id": task_id},
        )
        return False
    return True


def revert_merge_commit(task_id: str, project_root: str) -> bool:
    """Revert the most recent merge commit.

    Args:
        task_id: Task ID for logging
        project_root: Path to project root directory

    Returns:
        True if revert succeeded, False otherwise
    """
    from app.storage import log_task_event

    result = subprocess.run(
        ["git", "revert", "--no-edit", "-m", "1", "HEAD"],
        cwd=project_root,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        log_task_event(
            task_id,
            f"Auto-rollback FAILED: could not revert merge: {result.stderr[:200]}",
        )
        logger.error(
            "Auto-rollback failed",
            extra={"task_id": task_id, "error": result.stderr[:200]},
        )
        return False
    return True
