"""Celery tasks for autonomous system maintenance and cleanup."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.celery_app import celery_app
from app.services.worktree_manager import get_worktree_manager
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


@celery_app.task(name="summitflow.cleanup_orphaned_worktrees")
def cleanup_orphaned_worktrees(max_age_hours: int = 24) -> dict[str, Any]:
    """Clean up orphaned worktrees that are older than max_age_hours.

    This task runs periodically to remove worktrees that:
    - Are older than max_age_hours (abandoned from crashed executions)
    - Belong to tasks no longer in 'running' status

    Args:
        max_age_hours: Maximum age in hours before cleanup (default 24)

    Returns:
        Dict with removed_count and any errors
    """
    from app.storage.projects import get_all_project_root_paths

    try:
        total_removed_by_age = 0
        total_removed_by_status = 0

        # Iterate over all projects
        for root_path in get_all_project_root_paths():
            worktree_manager = get_worktree_manager(Path(root_path))

            # First, cleanup by age (convert hours to days, minimum 1 day)
            max_age_days = max(1, max_age_hours // 24)
            cleanup_result = worktree_manager.cleanup_stale_worktrees(max_age_days=max_age_days)
            removed_by_age = len(cleanup_result.get("removed", []))
            total_removed_by_age += removed_by_age
            if removed_by_age:
                logger.info(f"Cleaned up {removed_by_age} stale worktrees by age in {root_path}")

            # Second, cleanup worktrees for tasks no longer running
            active_worktrees = worktree_manager.list_active_worktrees()

            for worktree in active_worktrees:
                task_id = worktree.task_id
                task = task_store.get_task(task_id)

                # Remove if task doesn't exist or is not in running/ai_reviewing
                reason = ""
                if not task:
                    reason = "task not found"
                elif task.get("status") not in ("running", "ai_reviewing"):
                    reason = f"task status is {task.get('status')}"

                if reason:  # reason being set means we should remove
                    try:
                        worktree_manager.remove_worktree(worktree.project_id, task_id)
                        total_removed_by_status += 1
                        logger.info(f"Cleaned up worktree for {task_id}: {reason}")
                    except Exception as e:
                        logger.warning(f"Failed to remove worktree for {task_id}: {e}")

        total_removed = total_removed_by_age + total_removed_by_status
        logger.info(
            f"Worktree cleanup complete: {total_removed} removed "
            f"(by_age={total_removed_by_age}, by_status={total_removed_by_status})"
        )

        return {
            "status": "success",
            "removed_count": total_removed,
            "removed_by_age": total_removed_by_age,
            "removed_by_status": total_removed_by_status,
        }

    except Exception as e:
        logger.error(f"Error in cleanup_orphaned_worktrees: {e}")
        return {"status": "error", "error": str(e), "removed_count": 0}
