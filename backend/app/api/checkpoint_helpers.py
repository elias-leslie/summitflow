"""Helper functions for the checkpoints API."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from cli.lib.checkpoint import SnapshotMeta, get_active_checkpoints
from cli.lib.checkpoint_branches import get_task_branches

from .checkpoint_models import BranchInfo, CheckpointResponse


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


def _serialize_checkpoint(meta: SnapshotMeta) -> dict[str, Any]:
    """Build API-facing checkpoint info from canonical checkpoint metadata."""
    return {
        "task_id": meta.task_id,
        "project_id": meta.project_id,
        "snapshot_path": meta.worktree_path or "",
        "base_branch": meta.base_branch,
        "created_at": meta.created_at,
        "claimed_by": meta.claimed_by,
        "size": "worktree",
        "age": _format_age(meta.created_at),
        "branches": get_task_branches(meta.task_id, project_id=meta.project_id),
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
    """Get active checkpoints for a project from the canonical checkpoint store."""
    return [_serialize_checkpoint(checkpoint) for checkpoint in get_active_checkpoints(project_id)]


def find_checkpoint_in_all_projects(task_id: str) -> dict[str, Any] | None:
    """Search all projects for an active checkpoint by task_id."""
    for checkpoint in get_active_checkpoints():
        if checkpoint.task_id == task_id:
            return _serialize_checkpoint(checkpoint)
    return None
