"""Background tasks for autonomous system maintenance and cleanup.

Includes:
- Task claim expiration handling
- Worktree cleanup for completed/cancelled tasks
- Merge and cleanup for approved SIMPLE tasks
"""

from __future__ import annotations

import logging
import subprocess
from typing import Any

from app.services.worktree import get_task_worktree, remove_task_worktree
from app.storage import tasks as task_store
from app.storage.projects import get_project_root_path

logger = logging.getLogger(__name__)


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
        task = task_store.get_task(task_id)
        if task and task.get("status") == "running":
            logger.warning(
                "merge_blocked_task_running",
                extra={"task_id": task_id},
            )
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

        # Step 5: Post-merge validation — run quality checks on merged main
        validation_passed = _run_post_merge_validation(
            task_id, project_root, project_id
        )

        # Step 6: Auto-rollback if validation fails
        if not validation_passed:
            rollback_result = _auto_rollback(
                task_id, project_root, project_id, task_branch
            )
            if rollback_result:
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


def _run_post_merge_validation(
    task_id: str, project_root: str, project_id: str
) -> bool:
    """Run quality checks on the merged main branch.

    Runs dt --quick (lint + type check) on the project after merge.
    Logs results to task events. Does not block the merge — validation
    failures are logged for visibility but the merge is already committed.

    Args:
        task_id: Task ID for logging
        project_root: Path to project root
        project_id: Project ID

    Returns:
        True if validation passed, False otherwise
    """
    from ...storage import log_task_event

    try:
        result = subprocess.run(
            ["dt", "--quick"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=120,
        )

        passed = result.returncode == 0
        if passed:
            log_task_event(task_id, "Post-merge validation: PASSED")
            logger.info("Post-merge validation passed", extra={"task_id": task_id})
        else:
            output = (result.stdout + result.stderr)[-500:]
            log_task_event(
                task_id,
                f"Post-merge validation: FAILED\n{output}",
            )
            logger.warning(
                "Post-merge validation failed",
                extra={"task_id": task_id, "output": output[:200]},
            )
        return passed

    except subprocess.TimeoutExpired:
        log_task_event(task_id, "Post-merge validation: TIMEOUT (120s)")
        logger.warning("Post-merge validation timed out", extra={"task_id": task_id})
        return False
    except Exception as e:
        log_task_event(task_id, f"Post-merge validation: ERROR - {e}")
        logger.warning(
            "Post-merge validation error",
            extra={"task_id": task_id, "error": str(e)},
        )
        return False


def _auto_rollback(
    task_id: str,
    project_root: str,
    project_id: str,
    task_branch: str,
) -> bool:
    """Auto-revert a merge commit when post-merge validation fails.

    Reverts the most recent merge commit (HEAD), creates a regression fix task,
    and stores the rollback pattern as a memory episode.

    Args:
        task_id: Source task ID that caused the regression
        project_root: Path to project root
        project_id: Project ID
        task_branch: The branch that was merged

    Returns:
        True if rollback succeeded, False otherwise
    """
    from app.storage import log_task_event
    from app.storage.tasks.core import create_task

    try:
        # Revert the merge commit (HEAD is the merge commit)
        revert_result = subprocess.run(
            ["git", "revert", "--no-edit", "-m", "1", "HEAD"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if revert_result.returncode != 0:
            log_task_event(
                task_id,
                f"Auto-rollback FAILED: could not revert merge: {revert_result.stderr[:200]}",
            )
            logger.error(
                "Auto-rollback failed",
                extra={"task_id": task_id, "error": revert_result.stderr[:200]},
            )
            return False

        log_task_event(
            task_id,
            f"Auto-rollback: Reverted merge of {task_branch} due to regression",
        )
        logger.info(
            "Auto-rollback succeeded",
            extra={"task_id": task_id, "task_branch": task_branch},
        )

        # Create regression fix task
        try:
            create_task(
                project_id=project_id,
                title=f"Fix regression from {task_id}",
                description=(
                    f"Auto-rollback triggered: merge of task {task_id} "
                    f"(branch {task_branch}) caused post-merge validation failure. "
                    f"The merge has been reverted. Fix the issues and re-merge."
                ),
                task_type="regression",
                priority=1,
                parent_task_id=task_id,
                autonomous=True,
            )
        except Exception as e:
            logger.warning(
                "Failed to create regression fix task",
                extra={"task_id": task_id, "error": str(e)},
            )

        # Update source task status
        task_store.update_task_status(task_id, "blocked")

        # Store rollback pattern in memory
        try:
            from app.services.agent_hub_client import get_sync_client

            client = get_sync_client()
            client.save_learning(
                f"Merge of task {task_id} (branch {task_branch}) was auto-reverted "
                f"due to post-merge validation failure. Ensure all quality checks "
                f"pass before merging.",
                injection_tier="guardrail",
                confidence=85,
                context=f"task:{task_id} rollback",
                scope="project",
                scope_id=project_id,
            )
        except Exception:
            pass  # Non-critical

        return True

    except subprocess.TimeoutExpired:
        log_task_event(task_id, "Auto-rollback: git revert timed out")
        return False
    except Exception as e:
        log_task_event(task_id, f"Auto-rollback ERROR: {e}")
        logger.error(
            "Auto-rollback error",
            extra={"task_id": task_id, "error": str(e)},
        )
        return False
