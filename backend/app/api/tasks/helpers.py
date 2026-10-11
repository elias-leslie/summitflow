"""Tasks API - Helper functions for task operations."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from ...logging_config import get_logger
from ...storage import tasks as task_store

logger = get_logger(__name__)


def get_checkpoint_branch(task_id: str, project_id: str | None = None) -> str | None:
    """Return the legacy checkpoint branch for a task, if one exists."""
    from cli.lib.checkpoint import get_snapshot_info

    info = get_snapshot_info(task_id)
    if not info:
        return None
    if project_id and str(info.get("project_id") or "") != project_id:
        return None
    branch = info.get("branch")
    if not isinstance(branch, str) or not branch.strip():
        return None
    return branch


def has_active_checkpoint(task_id: str, project_id: str | None = None) -> bool:
    """Return True when a task has active checkpoint metadata."""
    from cli.lib.checkpoint import get_snapshot_info

    info = get_snapshot_info(task_id)
    if not info:
        return False
    return not (project_id and str(info.get("project_id") or "") != project_id)


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
