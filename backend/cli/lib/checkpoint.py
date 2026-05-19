"""Checkpoint library for st CLI.

Used by st claim, st done, st abandon, and st checkpoints commands.
Checkpoints record task metadata; work commits direct to main with
file-level coordination via `st lease`.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from app.storage.projects import get_project_root_path

from .checkpoint_branches import (
    delete_subtask_branch,
    delete_task_branches,
    get_remote_task_branches,
    get_task_branches,
)
from .checkpoint_metadata import (
    SnapshotMeta,
    _global_checkpoints_base,
    get_claimed_by,
    get_current_branch,
    get_meta_path,
    get_snapshots_dir,
    load_snapshot_meta,
    save_snapshot_meta,
)

__all__ = [
    "SnapshotMeta",
    "create_task_snapshot",
    "delete_subtask_branch", "delete_task_branches",
    "get_active_checkpoints", "get_remote_task_branches", "get_snapshot_info",
    "get_stale_checkpoints",
    "has_active_task",
    "remove_snapshot",
]


def create_task_snapshot(task_id: str, project_id: str) -> SnapshotMeta:
    """Create a checkpoint record for a task."""
    meta_path = get_meta_path(task_id, project_id=project_id)
    base_branch = get_current_branch()
    project_root = get_project_root_path(project_id)
    base_commit = _current_head(project_root) if project_root else None

    if meta_path.exists():
        print(f"Error: Checkpoint already exists for {task_id}", file=sys.stderr)
        print("Use 'st abandon' to remove existing checkpoint first.", file=sys.stderr)
        sys.exit(1)

    if project_root:
        try:
            from .autosnapshot import ensure_baseline

            ensure_baseline(project_id=project_id, cwd=project_root, source="auto-claim")
        except Exception:
            pass  # baseline is supplementary, never blocks claim

    meta = SnapshotMeta(
        task_id=task_id, project_id=project_id, base_branch=base_branch,
        created_at=datetime.now(UTC).isoformat(), claimed_by=get_claimed_by(),
        base_commit=base_commit,
    )
    save_snapshot_meta(meta)
    return meta


def remove_snapshot(task_id: str, project_id: str | None = None) -> bool:
    """Delete checkpoint metadata."""
    if project_id is None:
        meta = load_snapshot_meta(task_id)
        if not meta:
            return True
        project_id = meta.project_id
    meta_path = get_meta_path(task_id, project_id=project_id)
    meta_path.unlink(missing_ok=True)
    return True


def remove_checkpoint_for_scope_path(
    scope_path: str | Path,
    *,
    project_id: str | None = None,
) -> bool:
    """Delete checkpoint metadata associated with a legacy scoped path."""
    task_id = Path(scope_path).name
    meta = load_snapshot_meta(task_id)
    if not meta:
        return False
    if project_id and meta.project_id != project_id:
        return False
    return remove_snapshot(task_id, project_id=meta.project_id)


def get_active_checkpoints(project_id: str | None = None) -> list[SnapshotMeta]:
    """List active checkpoints, optionally filtered by project, newest first."""
    checkpoints = [checkpoint for checkpoint in _iter_checkpoint_meta(project_id) if _checkpoint_is_active(checkpoint)]
    checkpoints.sort(key=lambda meta: meta.created_at, reverse=True)
    return checkpoints


def get_stale_checkpoints(project_id: str | None = None) -> list[SnapshotMeta]:
    """Return checkpoint metadata whose recorded lane no longer resolves cleanly."""
    return [checkpoint for checkpoint in _iter_checkpoint_meta(project_id) if not _checkpoint_is_active(checkpoint)]


def has_active_task(project_id: str) -> str | None:
    """Return task_id if a task is already claimed for project, else None."""
    checkpoints = get_active_checkpoints(project_id)
    return checkpoints[0].task_id if checkpoints else None


def get_snapshot_info(task_id: str) -> dict[str, str | int | None] | None:
    """Return checkpoint info dict for task_id, or None if not found."""
    meta = load_snapshot_meta(task_id)
    if not meta:
        return None

    info: dict[str, str | int | None] = dict(meta.to_dict())
    task_branch = next(
        (
            branch["branch"]
            for branch in get_task_branches(task_id, project_id=meta.project_id)
            if branch.get("type") == "task"
        ),
        None,
    )
    info["branch"] = task_branch
    return info


def _checkpoint_is_active(checkpoint: SnapshotMeta) -> bool:
    """Return True when checkpoint metadata still represents an open claim."""
    return _task_status(checkpoint.task_id) not in _TERMINAL_TASK_STATUSES


_MISSING_TASK_STATUS = "__missing__"
_TERMINAL_TASK_STATUSES = {
    "completed",
    "failed",
    "cancelled",
    "abandoned",
    "closed",
    _MISSING_TASK_STATUS,
}


def _task_status(task_id: str) -> str | None:
    try:
        from app.storage.tasks import get_task
    except Exception:
        return None
    try:
        task = get_task(task_id)
    except Exception:
        return None
    if not task:
        return _MISSING_TASK_STATUS
    return str(task.get("status") or "").strip().lower() or None


def _current_head(project_root: str | None) -> str | None:
    if not project_root:
        return None
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=project_root,
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _iter_checkpoint_meta(project_id: str | None = None) -> list[SnapshotMeta]:
    """Load raw checkpoint metadata from the canonical global checkpoint store."""
    snapshots_dir = get_snapshots_dir(project_id=project_id) if project_id else _global_checkpoints_base()
    if not snapshots_dir.exists():
        return []

    checkpoints: list[SnapshotMeta] = []
    pattern = "*.meta.json" if project_id else "*/*.meta.json"
    for meta_file in snapshots_dir.glob(pattern):
        try:
            checkpoint = SnapshotMeta.from_dict(json.loads(meta_file.read_text()))
        except (json.JSONDecodeError, KeyError):
            continue
        if project_id is None or checkpoint.project_id == project_id:
            checkpoints.append(checkpoint)
    return checkpoints
