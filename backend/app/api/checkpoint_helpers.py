"""Helper functions for the checkpoints API."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.logging_config import get_logger
from app.storage.projects import get_project_root_path, list_projects

from .checkpoint_models import BranchInfo, CheckpointResponse

logger = get_logger(__name__)


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
            if not branch:
                continue
            if "/" in branch:
                parts = branch.split("/")
                subtask_id = parts[-1] if len(parts) > 1 else ""
                branches.append({"branch": branch, "subtask_id": subtask_id, "type": "subtask"})
            else:
                branches.append({"branch": branch, "subtask_id": "", "type": "task"})
    except subprocess.CalledProcessError as exc:
        logger.debug("Failed to list task branches", task_id=task_id, error=str(exc))
    return branches


def _format_age(created_at: str) -> str:
    """Format age from ISO timestamp to human-readable string."""
    try:
        created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        age = datetime.now(UTC) - created
        hours = int(age.total_seconds() / 3600)
        mins = int((age.total_seconds() % 3600) / 60)
        if hours >= 24:
            return f"{hours // 24}d ago"
        if hours > 0:
            return f"{hours}h ago"
        return f"{mins}m ago"
    except (ValueError, TypeError):
        return "unknown"


def _format_size(snapshot_path: Path) -> str:
    """Format file size to human-readable string."""
    if not snapshot_path.exists():
        return "0"
    size_bytes = snapshot_path.stat().st_size
    if size_bytes < 1024:
        return f"{size_bytes}B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes // 1024}KB"
    return f"{size_bytes // (1024 * 1024)}MB"


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

    return {
        "task_id": meta.get("task_id", task_id),
        "project_id": meta.get("project_id", ""),
        "snapshot_path": meta.get("snapshot_path", str(snapshot_path)),
        "base_branch": meta.get("base_branch", "main"),
        "created_at": meta.get("created_at", ""),
        "claimed_by": meta.get("claimed_by", "unknown"),
        "size": _format_size(snapshot_path),
        "age": _format_age(meta.get("created_at", "")),
    }


def _build_response(info: dict[str, Any]) -> CheckpointResponse:
    """Build a CheckpointResponse from a raw info dict."""
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


def get_project_checkpoints(project_id: str) -> list[dict[str, Any]]:
    """Get all checkpoints for a project, sorted newest first."""
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

    checkpoints.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return checkpoints


def find_checkpoint_in_all_projects(task_id: str) -> dict[str, Any] | None:
    """Search all projects for a checkpoint by task_id."""
    for proj in list_projects():
        proj_id = proj.get("id") or proj.get("project_id")
        if not proj_id:
            continue
        root = get_project_root_path(proj_id)
        if not root:
            continue
        info = _get_snapshot_info(task_id, Path(root))
        if info:
            info["branches"] = _get_task_branches(task_id, Path(root))
            return info
    return None
