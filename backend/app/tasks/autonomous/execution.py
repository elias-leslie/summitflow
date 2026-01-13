"""Celery task for autonomous work pickup and execution.

Uses OrchestratorService (Sonnet coordinator with Flash workers) for execution.
Respects time windows and concurrency limits from project's agent_configs.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
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

# Valid task types for autonomous execution
AUTONOMOUS_TASK_TYPES = frozenset({"task", "bug", "feature", "refactor", "debt", "regression"})


@celery_app.task(name="summitflow.autonomous_work_pickup")  # type: ignore[untyped-decorator]
def autonomous_work_pickup(project_id: str) -> dict[str, Any]:
    """Pick up and execute eligible tasks autonomously.

    Finds tasks that:
    - tier <= 3 (mechanical, not architectural)
    - status in (pending, paused, failed)
    - task_type in (task, bug, feature, refactor, debt, regression)
    - Pass all exclusion criteria
    - Within time window (start_hour <= current_hour < end_hour)
    - Under concurrency limit (max_concurrent)

    Uses OrchestratorService (Sonnet coordinator with Flash workers) for execution.

    Args:
        project_id: Project to pick up work for

    Returns:
        Dict with execution results and exclusion stats
    """
    from app.services.orchestrator import OrchestratorService
    from app.storage.agent_configs import (
        get_autonomous_schedule,
        is_autonomous_enabled,
        is_within_autonomous_hours,
    )

    try:
        # Check if autonomous execution is enabled
        if not is_autonomous_enabled(project_id):
            logger.debug(f"Autonomous execution disabled for {project_id}")
            return {"status": "disabled", "reason": "autonomous_enabled=false"}

        # Check time window
        current_hour = datetime.now(UTC).hour
        if not is_within_autonomous_hours(project_id, current_hour):
            schedule = get_autonomous_schedule(project_id)
            logger.debug(
                f"Outside autonomous hours for {project_id}: "
                f"current={current_hour}, window={schedule['start_hour']}-{schedule['end_hour']}"
            )
            return {
                "status": "outside_hours",
                "current_hour": current_hour,
                "start_hour": schedule["start_hour"],
                "end_hour": schedule["end_hour"],
            }

        # Check concurrency limit
        schedule = get_autonomous_schedule(project_id)
        max_concurrent = schedule["max_concurrent"]
        running_count = task_store.count_running_tasks(project_id)

        if running_count >= max_concurrent:
            logger.debug(
                f"Concurrency limit reached for {project_id}: "
                f"running={running_count}, max={max_concurrent}"
            )
            return {
                "status": "concurrency_limit",
                "running_count": running_count,
                "max_concurrent": max_concurrent,
            }

        # In validation mode, fetch allowed tasks directly (bypass limit)
        if VALIDATION_MODE and ALLOWED_TASK_IDS:
            eligible_tasks = []
            for task_id in ALLOWED_TASK_IDS:
                task = task_store.get_task(task_id)
                if task and task.get("status") in ("pending", "paused", "failed"):
                    tier = task.get("tier") or 2
                    task_type = task.get("task_type", "task")
                    if tier <= 3 and task_type in AUTONOMOUS_TASK_TYPES:
                        eligible_tasks.append(task)
            if not eligible_tasks:
                return {
                    "status": "no_allowed_tasks_ready",
                    "allowed_ids": ALLOWED_TASK_IDS,
                }
        else:
            # Normal mode: Get ready tasks with tier <= 3
            ready_tasks = task_store.list_ready_tasks(project_id, limit=50)

            # Filter by tier, status, and task type
            eligible_tasks = [
                t
                for t in ready_tasks
                if (t.get("tier") or 2) <= 3
                and t.get("status") in ("pending", "paused", "failed")
                and t.get("task_type", "task") in AUTONOMOUS_TASK_TYPES
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
                "task_type": selected_task.get("task_type", "task"),
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

        logger.info(
            f"Starting orchestrator for task {selected_task['id']} "
            f"(type={selected_task.get('task_type', 'task')})"
        )

        # Execute via OrchestratorService
        try:
            repo_path = get_project_repo_path(project_id)
            orchestrator = OrchestratorService(
                project_id=project_id,
                repo_path=repo_path,
                ws_task_id=selected_task["id"],
            )

            # Run the async coordinate method in the sync Celery task
            result = asyncio.run(orchestrator.coordinate(selected_task["id"]))

            if result.success:
                logger.info(
                    f"Task {selected_task['id']} orchestrated successfully, "
                    f"state={result.state.value}"
                )
                return {
                    "status": "success",
                    "task_id": selected_task["id"],
                    "task_type": selected_task.get("task_type", "task"),
                    "state": result.state.value,
                    "total_iterations": result.total_iterations,
                    "subtask_results": len(result.subtask_results),
                    "exclusion_stats": exclusion_stats,
                }
            else:
                logger.warning(f"Task {selected_task['id']} orchestration failed: {result.error}")
                return {
                    "status": "orchestration_failed",
                    "task_id": selected_task["id"],
                    "state": result.state.value,
                    "error": result.error,
                    "worktree_reverted": result.worktree_reverted,
                    "exclusion_stats": exclusion_stats,
                }

        except Exception as exec_error:
            # Cleanup worktree on error
            try:
                repo_path = get_project_repo_path(project_id)
                worktree_manager = get_worktree_manager(repo_path)
                worktree_manager.remove_worktree(project_id, selected_task["id"])
                logger.info(f"Cleaned up worktree for errored task {selected_task['id']}")
            except Exception as cleanup_err:
                logger.warning(f"Worktree cleanup failed: {cleanup_err}")

            logger.error(f"Execution error for task {selected_task['id']}: {exec_error}")
            return {
                "status": "execution_error",
                "task_id": selected_task["id"],
                "error": str(exec_error),
                "exclusion_stats": exclusion_stats,
            }

    except Exception as e:
        logger.error(f"Error in autonomous_work_pickup: {e}")
        return {"status": "error", "error": str(e)}
