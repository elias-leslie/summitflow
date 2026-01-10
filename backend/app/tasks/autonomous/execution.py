"""Celery task for autonomous work pickup and execution."""

from __future__ import annotations

import logging
from typing import Any

from app.celery_app import celery_app
from app.services.worktree_manager import get_worktree_manager
from app.storage import tasks as task_store

from .task_filters import (
    ALLOWED_TASK_IDS,
    AUTONOMOUS_DRY_RUN,
    VALIDATION_MODE,
    check_exclusion,
)
from .utils import get_project_repo_path

logger = logging.getLogger(__name__)


@celery_app.task(name="summitflow.autonomous_work_pickup")  # type: ignore[untyped-decorator]
def autonomous_work_pickup(project_id: str) -> dict[str, Any]:
    """Pick up and execute eligible tasks autonomously.

    Finds tasks that:
    - tier <= 3 (mechanical, not architectural)
    - status in (pending, paused, failed)
    - Pass all exclusion criteria

    Claims one task atomically and executes it via ImplementationExecutor.

    Args:
        project_id: Project to pick up work for

    Returns:
        Dict with execution results and exclusion stats
    """
    from app.services.implementation import ImplementationExecutor
    from app.storage.agent_configs import is_autonomous_enabled

    try:
        # Check if autonomous execution is enabled
        if not is_autonomous_enabled(project_id):
            logger.debug(f"Autonomous execution disabled for {project_id}")
            return {"status": "disabled", "reason": "autonomous_enabled=false"}

        # In validation mode, fetch allowed tasks directly (bypass limit)
        if VALIDATION_MODE and ALLOWED_TASK_IDS:
            eligible_tasks = []
            for task_id in ALLOWED_TASK_IDS:
                task = task_store.get_task(task_id)
                if task and task.get("status") in ("pending", "paused", "failed"):
                    tier = task.get("tier") or 2
                    if tier <= 3:
                        eligible_tasks.append(task)
            if not eligible_tasks:
                return {
                    "status": "no_allowed_tasks_ready",
                    "allowed_ids": ALLOWED_TASK_IDS,
                }
        else:
            # Normal mode: Get ready tasks with tier <= 3
            ready_tasks = task_store.list_ready_tasks(project_id, limit=50)

            # Filter by tier and status
            eligible_tasks = [
                t
                for t in ready_tasks
                if (t.get("tier") or 2) <= 3 and t.get("status") in ("pending", "paused", "failed")
            ]

            if not eligible_tasks:
                return {"status": "no_work", "tasks_checked": len(ready_tasks)}

        # Apply exclusion criteria
        exclusion_stats: dict[str, int] = {}
        selected_task = None

        for task in eligible_tasks:
            exclusion_reason = check_exclusion(task)
            if exclusion_reason:
                logger.debug(f"Excluded task {task['id']}: {exclusion_reason}")
                exclusion_stats[exclusion_reason] = exclusion_stats.get(exclusion_reason, 0) + 1
            else:
                selected_task = task
                break  # Take first eligible task

        if not selected_task:
            return {
                "status": "all_excluded",
                "tasks_checked": len(eligible_tasks),
                "exclusion_stats": exclusion_stats,
            }

        # Dry-run mode: log what would execute but don't actually run
        if AUTONOMOUS_DRY_RUN:
            logger.info(
                f"DRY_RUN: Would execute {selected_task['id']}: {selected_task['title'][:60]}"
            )
            return {
                "status": "dry_run",
                "task_id": selected_task["id"],
                "title": selected_task["title"],
                "exclusion_stats": exclusion_stats,
            }

        # Validation mode: only execute tasks in allowlist
        if VALIDATION_MODE and selected_task["id"] not in ALLOWED_TASK_IDS:
            logger.info(f"VALIDATION: Skipping {selected_task['id']} (not in allowlist)")
            return {
                "status": "validation_skip",
                "task_id": selected_task["id"],
                "title": selected_task["title"],
                "exclusion_stats": exclusion_stats,
            }

        # Claim task atomically
        worker_id = f"autonomous-{project_id}"
        claimed = task_store.claim_task(selected_task["id"], worker_id, lock_duration_minutes=60)

        if not claimed:
            logger.info(f"Failed to claim task {selected_task['id']} - already claimed")
            return {"status": "claim_failed", "task_id": selected_task["id"]}

        logger.info(f"Claimed task {claimed['id']} for autonomous execution")

        # Execute via ImplementationExecutor with worktree isolation
        # TODO: Make use_worktree configurable via agent_configs when stabilized
        executor = ImplementationExecutor(project_id, use_worktree=True)

        try:
            session_id = executor.start_execution(claimed["id"], agent_type="gemini")
            result = executor.execute_next_task(session_id, max_iterations=5)

            if result.success:
                # Transition to ai_reviewing for Opus gate
                task_store.update_task_status(claimed["id"], "ai_reviewing")
                logger.info(f"Task {claimed['id']} succeeded, moved to ai_reviewing")
                return {
                    "status": "success",
                    "task_id": claimed["id"],
                    "iterations": result.iterations,
                    "model_used": result.model_used,
                    "exclusion_stats": exclusion_stats,
                }
            else:
                # Mark failed with error message
                task_store.update_task_status(
                    claimed["id"],
                    "failed",
                    error_message=result.reason or result.error or "Unknown error",
                )
                task_store.release_task(claimed["id"])

                # Cleanup worktree on failure
                try:
                    repo_path = get_project_repo_path(project_id)
                    worktree_manager = get_worktree_manager(repo_path)
                    worktree_manager.remove_worktree(project_id, claimed["id"])
                    logger.info(f"Cleaned up worktree for failed task {claimed['id']}")
                except Exception as cleanup_err:
                    logger.warning(f"Worktree cleanup failed: {cleanup_err}")

                logger.warning(f"Task {claimed['id']} failed: {result.reason}")
                return {
                    "status": "execution_failed",
                    "task_id": claimed["id"],
                    "iterations": result.iterations,
                    "reason": result.reason,
                    "error": result.error,
                    "exclusion_stats": exclusion_stats,
                }

        except Exception as exec_error:
            # Release task on execution error
            task_store.release_task(claimed["id"])

            # Cleanup worktree on error
            try:
                repo_path = get_project_repo_path(project_id)
                worktree_manager = get_worktree_manager(repo_path)
                worktree_manager.remove_worktree(project_id, claimed["id"])
                logger.info(f"Cleaned up worktree for errored task {claimed['id']}")
            except Exception as cleanup_err:
                logger.warning(f"Worktree cleanup failed: {cleanup_err}")

            logger.error(f"Execution error for task {claimed['id']}: {exec_error}")
            return {
                "status": "execution_error",
                "task_id": claimed["id"],
                "error": str(exec_error),
                "exclusion_stats": exclusion_stats,
            }

    except Exception as e:
        logger.error(f"Error in autonomous_work_pickup: {e}")
        return {"status": "error", "error": str(e)}
