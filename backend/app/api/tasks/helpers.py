"""Tasks API - Helper functions.

Utility functions for task operations including:
- Worktree info retrieval
- Step count calculation
- Task validation
- Autonomous task dispatch
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from ...logging_config import get_logger
from ...storage import tasks as task_store
from ...storage.steps import STEP_STATUS_PLAN_DEFECT, get_steps_for_subtask
from ...storage.subtasks import get_subtasks_for_task

logger = get_logger(__name__)


def get_worktree_response(task_id: str) -> Any | None:
    """Get worktree info for a task if it exists.

    Args:
        task_id: Task ID to check for worktree

    Returns:
        WorktreeResponse if worktree exists, None otherwise
    """
    try:
        from ...cli.lib.worktree import get_worktree_info
        from ...schemas.tasks import WorktreeResponse

        worktree_info = get_worktree_info(task_id)
        if worktree_info:
            return WorktreeResponse(
                path=str(worktree_info.path),
                branch=worktree_info.branch,
                is_active=worktree_info.is_active,
            )
    except ImportError:
        # Worktree module not available
        pass
    except Exception as e:
        logger.debug("Failed to get worktree info", task_id=task_id, error=str(e))
    return None


def get_step_count_for_task(task_id: str) -> int:
    """Get total step count across all subtasks for a task.

    Returns 0 if no subtasks or steps exist.
    """
    subtasks = get_subtasks_for_task(task_id, include_steps=False)
    if not subtasks:
        return 0

    total = 0
    for subtask in subtasks:
        steps = get_steps_for_subtask(subtask.get("id", ""))
        total += len(steps)
    return total


def get_step_counts_batch(task_ids: list[str]) -> dict[str, int]:
    """Get step counts for multiple tasks.

    Returns dict mapping task_id to step count.
    """
    return {task_id: get_step_count_for_task(task_id) for task_id in task_ids}


def get_step_verification_status(task_id: str) -> dict[str, Any]:
    """Get step verification status for a task.

    Returns dict with:
    - total: int (total steps)
    - verified: int (passed steps, including plan_defect with completed fix)
    - unverified: list of step IDs that haven't passed
    - all_verified: bool
    """
    subtasks = get_subtasks_for_task(task_id, include_steps=False)
    if not subtasks:
        return {"total": 0, "verified": 0, "unverified": [], "all_verified": True}

    total = 0
    verified = 0
    unverified: list[str] = []

    for subtask in subtasks:
        subtask_id = subtask.get("id", "")
        steps = get_steps_for_subtask(subtask_id)
        for step in steps:
            total += 1
            step_id = f"{subtask_id}.{step.get('step_number', 0)}"
            if step.get("passes"):
                verified += 1
            elif step.get("status") == STEP_STATUS_PLAN_DEFECT and step.get("fix_step_number"):
                # Plan defect steps with linked fix step count as verified
                verified += 1
            else:
                unverified.append(step_id)

    return {
        "total": total,
        "verified": verified,
        "unverified": unverified,
        "all_verified": len(unverified) == 0,
    }


def verify_task_project(task_id: str, project_id: str) -> dict[str, Any]:
    """Get task and verify it belongs to the project.

    Args:
        task_id: Task ID to fetch
        project_id: Expected project ID

    Returns:
        Task dict if valid

    Raises:
        HTTPException(404): If task not found or belongs to different project
    """
    task = task_store.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    if task["project_id"] != project_id:
        raise HTTPException(
            status_code=404, detail=f"Task {task_id} not found in project {project_id}"
        )
    return task


def get_task_or_404(task_id: str) -> dict[str, Any]:
    """Get task by ID without project validation.

    Task IDs are globally unique, so project_id is not required.
    Use this for global endpoints where project context is not available.

    Args:
        task_id: Task ID to fetch

    Returns:
        Task dict

    Raises:
        HTTPException(404): If task not found
    """
    task = task_store.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return task


async def dispatch_autonomous_task(task_id: str, new_status: str, project_id: str) -> None:
    """Dispatch autonomous execution via Hatchet workflow based on status transition.

    Status triggers:
    - pending -> Idea triage (if task_type is 'idea')
    - queue -> Begin autonomous execution
    - cancelled/blocked (from running) -> Emergency stop
    """
    try:
        if new_status == "queue":
            from ...workflows.models import TaskInput
            from ...workflows.pipeline import execute_wf

            await execute_wf.aio_run_no_wait(TaskInput(task_id=task_id, project_id=project_id))
            logger.info("Dispatched autonomous execution", task_id=task_id, status=new_status)

        elif new_status == "pending":
            task = task_store.get_task(task_id)
            if task and task.get("task_type") == "idea":
                from ...workflows.models import TaskInput
                from ...workflows.pipeline import triage_wf

                await triage_wf.aio_run_no_wait(TaskInput(task_id=task_id, project_id=project_id))
                logger.info("Dispatched idea triage", task_id=task_id)

        elif new_status in ("cancelled", "blocked"):
            abort_running_task(task_id)

    except ImportError:
        logger.debug("Autonomous tasks not available")
    except Exception as e:
        logger.warning("Failed to dispatch autonomous task", task_id=task_id, error=str(e))


def abort_running_task(task_id: str) -> None:
    """Emergency stop - signal abort for a running task.

    Called when task is dragged out of running column (to cancelled/blocked).
    The task status update to cancelled/blocked prevents further subtask execution.
    Hatchet concurrency limits prevent re-dispatch of the same task.
    """
    logger.info("Task abort requested", task_id=task_id)
