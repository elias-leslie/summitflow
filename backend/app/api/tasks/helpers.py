"""Tasks API - Helper functions for task operations."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from ...logging_config import get_logger
from ...schemas.task_response_models import WorktreeResponse
from ...storage import tasks as task_store

logger = get_logger(__name__)


def _build_worktree_response(task_id: str) -> WorktreeResponse | None:
    """Build WorktreeResponse from worktree info, or return None if not found."""
    from ...cli.lib.worktree import get_worktree_info
    worktree_info = get_worktree_info(task_id)
    if not worktree_info:
        return None
    return WorktreeResponse(
        path=str(worktree_info.path),
        branch=worktree_info.branch,
        is_active=worktree_info.is_active,
    )


def get_worktree_response(task_id: str) -> WorktreeResponse | None:
    """Get worktree info for a task if it exists, or None."""
    try:
        return _build_worktree_response(task_id)
    except ImportError:
        pass
    except Exception as e:
        logger.debug("Failed to get worktree info", task_id=task_id, error=str(e))
    return None


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
    """Route dispatch based on new_status: pending, or cancelled/failed."""
    if new_status == "pending":
        await _dispatch_queue(task_id, project_id)
        await _dispatch_pending_idea(task_id, project_id)
    elif new_status in ("cancelled", "failed"):
        abort_running_task(task_id)


async def dispatch_autonomous_task(task_id: str, new_status: str, project_id: str) -> None:
    """Dispatch autonomous execution via Hatchet workflow based on status transition."""
    try:
        await _route_dispatch(task_id, new_status, project_id)
    except ImportError:
        logger.debug("Autonomous tasks not available")
    except Exception as e:
        logger.warning("Failed to dispatch autonomous task", task_id=task_id, error=str(e))


async def refresh_task_tracking(task_id: str, source: str) -> dict[str, Any]:
    """Refresh task, sync second-opinion tracking and execution readiness, return updated task.

    Consolidates the repeated pattern of:
    1. Refresh task from storage
    2. Ensure second-opinion tracking
    3. Sync execution readiness
    4. Return freshly loaded task
    """
    import asyncio

    from ...services.task_execution_readiness import sync_task_execution_readiness
    from ...services.task_second_opinion import ensure_second_opinion_tracking

    task = await asyncio.to_thread(task_store.get_task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found after mutation")
    await asyncio.to_thread(ensure_second_opinion_tracking, task_id, task, None, source=source)
    await asyncio.to_thread(sync_task_execution_readiness, task_id, source)
    refreshed = await asyncio.to_thread(task_store.get_task, task_id)
    return refreshed if refreshed else task


def abort_running_task(task_id: str) -> None:
    """Emergency stop - publish abort signal via Redis pub/sub for running task."""
    from ...services.pubsub import publish_ws_event

    logger.info("Task abort requested", task_id=task_id)
    published = publish_ws_event(
        task_id,
        {"type": "stop_signal", "data": {"source": "status_change"}},
    )
    if not published:
        logger.warning("Failed to publish abort signal", task_id=task_id)
