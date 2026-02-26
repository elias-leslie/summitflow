"""Checkpoints API - checkpoint status for frontend UI.

Provides checkpoint information for the dashboard and task detail views.
Reads from .st/snapshots directory in project roots.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from app.storage.projects import get_project_root_path, list_projects

from .checkpoint_helpers import (
    _build_response,
    _get_snapshot_info,
    _get_task_branches,
    find_checkpoint_in_all_projects,
    get_project_checkpoints,
)
from .checkpoint_models import BranchInfo, CheckpointResponse, CheckpointsListResponse

__all__ = [
    "BranchInfo",
    "CheckpointResponse",
    "CheckpointsListResponse",
    "router",
]

router = APIRouter(prefix="/api/checkpoints", tags=["checkpoints"])


@router.get("", response_model=CheckpointsListResponse)
async def list_checkpoints(project_id: str | None = None) -> CheckpointsListResponse:
    """List all active checkpoints.

    Args:
        project_id: Optional filter by project ID

    Returns:
        List of checkpoints with details
    """
    all_checkpoints: list[dict[str, Any]] = []

    if project_id:
        all_checkpoints = get_project_checkpoints(project_id)
    else:
        for proj in list_projects():
            proj_id = proj.get("id") or proj.get("project_id")
            if proj_id:
                all_checkpoints.extend(get_project_checkpoints(proj_id))

    all_checkpoints.sort(key=lambda x: x.get("created_at", ""), reverse=True)

    return CheckpointsListResponse(
        checkpoints=[_build_response(cp) for cp in all_checkpoints],
        total=len(all_checkpoints),
    )


@router.get("/{task_id}", response_model=CheckpointResponse)
async def get_checkpoint(task_id: str, project_id: str | None = None) -> CheckpointResponse:
    """Get checkpoint details for a specific task.

    Args:
        task_id: Task identifier
        project_id: Project ID (required if task could be in multiple projects)

    Returns:
        Checkpoint details with branch info

    Raises:
        HTTPException: If checkpoint not found
    """
    if project_id:
        root = get_project_root_path(project_id)
        if not root:
            raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
        info = _get_snapshot_info(task_id, Path(root))
        if info:
            info["branches"] = _get_task_branches(task_id, Path(root))
            return _build_response(info)
    else:
        info = find_checkpoint_in_all_projects(task_id)
        if info:
            return _build_response(info)

    raise HTTPException(status_code=404, detail=f"Checkpoint not found for task {task_id}")


@router.get("/project/{project_id}/active", response_model=CheckpointResponse | None)
async def get_active_checkpoint(project_id: str) -> CheckpointResponse | None:
    """Get the active checkpoint for a project.

    Each project can only have one active task (project-level lock).

    Args:
        project_id: Project identifier

    Returns:
        Active checkpoint or None if no checkpoint is active
    """
    checkpoints = get_project_checkpoints(project_id)
    if not checkpoints:
        return None
    return _build_response(checkpoints[0])
