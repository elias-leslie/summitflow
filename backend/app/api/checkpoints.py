"""Checkpoints API - checkpoint status for frontend UI.

Provides checkpoint information for the dashboard and task detail views.
Reads from .st/snapshots directory in project roots.
"""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.storage.projects import get_project_root_path, list_projects

router = APIRouter(prefix="/api/checkpoints", tags=["checkpoints"])


class BranchInfo(BaseModel):
    """Git branch information."""

    branch: str
    subtask_id: str
    type: str  # "task" or "subtask"


class CheckpointResponse(BaseModel):
    """Checkpoint details response."""

    task_id: str
    project_id: str
    snapshot_path: str
    base_branch: str
    created_at: str
    claimed_by: str
    size: str
    age: str
    branches: list[BranchInfo]


class CheckpointsListResponse(BaseModel):
    """List of checkpoints response."""

    checkpoints: list[CheckpointResponse]
    total: int


def _get_task_branches(task_id: str, project_path: Path) -> list[dict[str, str]]:
    """Get all branches for a task (task branch + subtask branches)."""
    branches = []
    try:
        result = subprocess.run(
            ["git", "branch", "--list", f"{task_id}*"],
            capture_output=True,
            text=True,
            check=True,
            cwd=project_path,
        )
        for line in result.stdout.splitlines():
            branch = line.strip().lstrip("* ")
            if branch:
                if "/" in branch:
                    parts = branch.split("/")
                    subtask_id = parts[-1] if len(parts) > 1 else ""
                    branches.append(
                        {"branch": branch, "subtask_id": subtask_id, "type": "subtask"}
                    )
                else:
                    branches.append({"branch": branch, "subtask_id": "", "type": "task"})
    except subprocess.CalledProcessError:
        pass
    return branches


def _format_age(created_at: str) -> str:
    """Format age from ISO timestamp to human-readable string."""
    try:
        created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        age = datetime.now(UTC) - created
        hours = int(age.total_seconds() / 3600)
        mins = int((age.total_seconds() % 3600) / 60)

        if hours >= 24:
            days = hours // 24
            return f"{days}d ago"
        elif hours > 0:
            return f"{hours}h ago"
        else:
            return f"{mins}m ago"
    except (ValueError, TypeError):
        return "unknown"


def _get_snapshot_info(task_id: str, project_path: Path) -> dict[str, Any] | None:
    """Get snapshot info for a task from .st/snapshots directory."""
    meta_path = project_path / ".st" / "snapshots" / f"{task_id}.meta.json"
    snapshot_path = project_path / ".st" / "snapshots" / f"{task_id}.sql"

    if not meta_path.exists():
        return None

    try:
        meta = json.loads(meta_path.read_text())
    except (json.JSONDecodeError, OSError):
        return None

    info = {
        "task_id": meta.get("task_id", task_id),
        "project_id": meta.get("project_id", ""),
        "snapshot_path": meta.get("snapshot_path", str(snapshot_path)),
        "base_branch": meta.get("base_branch", "main"),
        "created_at": meta.get("created_at", ""),
        "claimed_by": meta.get("claimed_by", "unknown"),
    }

    # Add size info
    if snapshot_path.exists():
        size_bytes = snapshot_path.stat().st_size
        if size_bytes < 1024:
            info["size"] = f"{size_bytes}B"
        elif size_bytes < 1024 * 1024:
            info["size"] = f"{size_bytes // 1024}KB"
        else:
            info["size"] = f"{size_bytes // (1024 * 1024)}MB"
    else:
        info["size"] = "0"

    info["age"] = _format_age(info["created_at"])

    return info


def _get_project_checkpoints(project_id: str) -> list[dict[str, Any]]:
    """Get all checkpoints for a project."""
    root = get_project_root_path(project_id)
    if not root:
        return []

    project_path = Path(root)
    snapshots_dir = project_path / ".st" / "snapshots"
    if not snapshots_dir.exists():
        return []

    checkpoints = []
    for meta_file in snapshots_dir.glob("*.meta.json"):
        task_id = meta_file.stem.replace(".meta", "")
        info = _get_snapshot_info(task_id, project_path)
        if info:
            info["branches"] = _get_task_branches(task_id, project_path)
            checkpoints.append(info)

    # Sort by creation time, newest first
    checkpoints.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return checkpoints


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
        all_checkpoints = _get_project_checkpoints(project_id)
    else:
        # Get checkpoints from all projects
        projects = list_projects()
        for proj in projects:
            proj_id = proj.get("id") or proj.get("project_id")
            if proj_id:
                all_checkpoints.extend(_get_project_checkpoints(proj_id))

    # Sort all by creation time
    all_checkpoints.sort(key=lambda x: x.get("created_at", ""), reverse=True)

    return CheckpointsListResponse(
        checkpoints=[
            CheckpointResponse(
                task_id=cp["task_id"],
                project_id=cp["project_id"],
                snapshot_path=cp["snapshot_path"],
                base_branch=cp["base_branch"],
                created_at=cp["created_at"],
                claimed_by=cp["claimed_by"],
                size=cp["size"],
                age=cp["age"],
                branches=[BranchInfo(**b) for b in cp.get("branches", [])],
            )
            for cp in all_checkpoints
        ],
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

        project_path = Path(root)
        info = _get_snapshot_info(task_id, project_path)
        if info:
            info["branches"] = _get_task_branches(task_id, project_path)
            return CheckpointResponse(
                task_id=info["task_id"],
                project_id=info["project_id"],
                snapshot_path=info["snapshot_path"],
                base_branch=info["base_branch"],
                created_at=info["created_at"],
                claimed_by=info["claimed_by"],
                size=info["size"],
                age=info["age"],
                branches=[BranchInfo(**b) for b in info.get("branches", [])],
            )
    else:
        # Search all projects for the checkpoint
        projects = list_projects()
        for proj in projects:
            proj_id = proj.get("id") or proj.get("project_id")
            if not proj_id:
                continue

            root = get_project_root_path(proj_id)
            if not root:
                continue

            project_path = Path(root)
            info = _get_snapshot_info(task_id, project_path)
            if info:
                info["branches"] = _get_task_branches(task_id, project_path)
                return CheckpointResponse(
                    task_id=info["task_id"],
                    project_id=info["project_id"],
                    snapshot_path=info["snapshot_path"],
                    base_branch=info["base_branch"],
                    created_at=info["created_at"],
                    claimed_by=info["claimed_by"],
                    size=info["size"],
                    age=info["age"],
                    branches=[BranchInfo(**b) for b in info.get("branches", [])],
                )

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
    checkpoints = _get_project_checkpoints(project_id)
    if not checkpoints:
        return None

    # Return the most recent (first after sort)
    cp = checkpoints[0]
    return CheckpointResponse(
        task_id=cp["task_id"],
        project_id=cp["project_id"],
        snapshot_path=cp["snapshot_path"],
        base_branch=cp["base_branch"],
        created_at=cp["created_at"],
        claimed_by=cp["claimed_by"],
        size=cp["size"],
        age=cp["age"],
        branches=[BranchInfo(**b) for b in cp.get("branches", [])],
    )
