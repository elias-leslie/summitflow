"""Tasks API - Helper functions for task operations."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from ...logging_config import get_logger
from ...storage import tasks as task_store
from ...storage.steps import STEP_STATUS_PLAN_DEFECT, get_steps_for_subtask
from ...storage.subtasks import get_subtasks_for_task

logger = get_logger(__name__)


def _build_worktree_response(task_id: str) -> Any | None:
    """Build WorktreeResponse from worktree info, or return None if not found."""
    from ...cli.lib.worktree import get_worktree_info
    from ...schemas.tasks import WorktreeResponse
    worktree_info = get_worktree_info(task_id)
    if not worktree_info:
        return None
    return WorktreeResponse(
        path=str(worktree_info.path),
        branch=worktree_info.branch,
        is_active=worktree_info.is_active,
    )


def get_worktree_response(task_id: str) -> Any | None:
    """Get worktree info for a task if it exists, or None."""
    try:
        return _build_worktree_response(task_id)
    except ImportError:
        pass
    except Exception as e:
        logger.debug("Failed to get worktree info", task_id=task_id, error=str(e))
    return None


def get_step_count_for_task(task_id: str) -> int:
    """Get total step count across all subtasks for a task. Returns 0 if none exist."""
    subtasks = get_subtasks_for_task(task_id, include_steps=False)
    if not subtasks:
        return 0
    return sum(len(get_steps_for_subtask(s.get("id", ""))) for s in subtasks)


def get_step_counts_batch(task_ids: list[str]) -> dict[str, int]:
    """Get step counts for multiple tasks. Returns dict mapping task_id to step count."""
    return {task_id: get_step_count_for_task(task_id) for task_id in task_ids}


def _step_is_verified(step: dict[str, Any]) -> bool:
    """Return True if step counts as verified."""
    return bool(step.get("passes") or (step.get("status") == STEP_STATUS_PLAN_DEFECT and step.get("fix_step_number")))


def _tally_subtask_steps(subtask_id: str) -> tuple[int, int, list[str]]:
    """Return (total, verified, unverified_ids) for all steps in a subtask."""
    unverified: list[str] = []
    steps = list(get_steps_for_subtask(subtask_id))
    verified = sum(1 for s in steps if _step_is_verified(s))
    for step in steps:
        if not _step_is_verified(step):
            unverified.append(f"{subtask_id}.{step.get('step_number', 0)}")
    return len(steps), verified, unverified


def get_step_verification_status(task_id: str) -> dict[str, Any]:
    """Get step verification status: total, verified, unverified IDs, all_verified."""
    subtasks = get_subtasks_for_task(task_id, include_steps=False)
    if not subtasks:
        return {"total": 0, "verified": 0, "unverified": [], "all_verified": True}
    total, verified, unverified = 0, 0, []
    for subtask in subtasks:
        sub_total, sub_verified, sub_unverified = _tally_subtask_steps(subtask.get("id", ""))
        total += sub_total
        verified += sub_verified
        unverified.extend(sub_unverified)
    return {"total": total, "verified": verified, "unverified": unverified, "all_verified": not unverified}


def verify_task_project(task_id: str, project_id: str) -> dict[str, Any]:
    """Get task and verify it belongs to the project. Raises HTTPException(404) if not found."""
    task = task_store.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    if task["project_id"] != project_id:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found in project {project_id}")
    return task


def get_task_or_404(task_id: str) -> dict[str, Any]:
    """Get task by ID without project validation. Raises HTTPException(404) if not found."""
    task = task_store.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return task


async def _dispatch_queue(task_id: str, project_id: str) -> None:
    """Dispatch task execution for queue status."""
    from ...services.dispatch import dispatch_task
    result = await dispatch_task(task_id, project_id)
    logger.info("Dispatched autonomous execution", task_id=task_id, stage=result.get("stage"))


async def _dispatch_pending_idea(task_id: str, project_id: str) -> None:
    """Dispatch idea triage if task type is 'idea'."""
    task = task_store.get_task(task_id)
    if not (task and task.get("task_type") == "idea"):
        return
    from ...workflows.models import TaskInput
    from ...workflows.pipeline import triage_wf
    await triage_wf.aio_run_no_wait(TaskInput(task_id=task_id, project_id=project_id))
    logger.info("Dispatched idea triage", task_id=task_id)


async def _route_dispatch(task_id: str, new_status: str, project_id: str) -> None:
    """Route dispatch based on new_status: queue, pending, or cancelled/blocked."""
    if new_status == "queue":
        await _dispatch_queue(task_id, project_id)
    elif new_status == "pending":
        await _dispatch_pending_idea(task_id, project_id)
    elif new_status in ("cancelled", "blocked"):
        abort_running_task(task_id)


async def dispatch_autonomous_task(task_id: str, new_status: str, project_id: str) -> None:
    """Dispatch autonomous execution via Hatchet workflow based on status transition."""
    try:
        await _route_dispatch(task_id, new_status, project_id)
    except ImportError:
        logger.debug("Autonomous tasks not available")
    except Exception as e:
        logger.warning("Failed to dispatch autonomous task", task_id=task_id, error=str(e))


def abort_running_task(task_id: str) -> None:
    """Emergency stop - signal abort for a running task."""
    logger.info("Task abort requested", task_id=task_id)
