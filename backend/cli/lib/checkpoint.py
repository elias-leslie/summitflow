"""Checkpoint library for st CLI — worktree isolation for safe task execution.

Used by st claim, st done, st abandon, and st checkpoints commands.
Worktree paths live at `/srv/workspaces/lanes/<project-id>/<task-id>/` when the
shared workspace is available and `~/.local/share/st/worktrees/<project-id>/<task-id>/`
otherwise.
"""

from __future__ import annotations

import contextlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from .checkpoint_branches import (
    create_subtask_branch,
    delete_subtask_branch,
    delete_task_branches,
    get_task_branches,
    merge_subtask_branch,
    merge_task_branch,
)
from .checkpoint_helpers import create_legacy_branch, create_worktree_resources
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
    "create_subtask_branch", "create_task_snapshot",
    "delete_subtask_branch", "delete_task_branches",
    "get_active_checkpoints", "get_snapshot_info",
    "get_stale_checkpoints",
    "has_active_task",
    "merge_subtask_branch", "merge_task_branch",
    "remove_checkpoint_for_worktree_path",
    "remove_snapshot",
]


def create_task_snapshot(task_id: str, project_id: str, use_worktree: bool = True) -> SnapshotMeta:
    """Create worktree checkpoint for task. Raises SystemExit on git errors."""
    meta_path = get_meta_path(task_id, project_id=project_id)
    base_branch = get_current_branch()

    if meta_path.exists():
        print(f"Error: Checkpoint already exists for {task_id}", file=sys.stderr)
        print("Use 'st abandon' to remove existing checkpoint first.", file=sys.stderr)
        sys.exit(1)

    worktree_path: str | None = None
    backend_port: int | None = None
    frontend_port: int | None = None

    if use_worktree:
        worktree_path, backend_port, frontend_port = create_worktree_resources(
            task_id, base_branch, project_id
        )
        if worktree_path:
            try:
                from .autosnapshot import ensure_baseline

                ensure_baseline(project_id=project_id, cwd=worktree_path, source="auto-claim")
            except Exception:
                pass  # baseline is supplementary, never blocks claim
    else:
        create_legacy_branch(task_id)

    meta = SnapshotMeta(
        task_id=task_id, project_id=project_id, base_branch=base_branch,
        created_at=datetime.now(UTC).isoformat(), claimed_by=get_claimed_by(),
        worktree_path=worktree_path, backend_port=backend_port, frontend_port=frontend_port,
    )
    save_snapshot_meta(meta)
    return meta


def remove_snapshot(
    task_id: str, remove_worktree: bool = True, project_id: str | None = None
) -> bool:
    """Delete checkpoint metadata and optionally the worktree."""
    from .port_manager import release_ports
    from .worktree import remove_worktree as rm_worktree

    if project_id is None:
        meta = load_snapshot_meta(task_id)
        if meta:
            project_id = meta.project_id
    meta_path = get_meta_path(task_id, project_id=project_id)

    if remove_worktree:
        with contextlib.suppress(Exception):
            rm_worktree(task_id, delete_branch=False, project_id=project_id)

    with contextlib.suppress(Exception):
        release_ports(task_id, project_id)

    meta_path.unlink(missing_ok=True)
    return True


def remove_checkpoint_for_worktree_path(
    worktree_path: str | Path,
    *,
    project_id: str | None = None,
) -> bool:
    """Delete checkpoint metadata whose recorded worktree path matches exactly."""
    target = Path(worktree_path).resolve()
    for checkpoint in _iter_checkpoint_meta(project_id):
        if not checkpoint.worktree_path:
            continue
        try:
            checkpoint_path = Path(checkpoint.worktree_path).resolve()
        except OSError:
            checkpoint_path = Path(checkpoint.worktree_path)
        if checkpoint_path == target:
            return remove_snapshot(
                checkpoint.task_id,
                remove_worktree=False,
                project_id=checkpoint.project_id,
            )
    return False


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
    from .port_manager import get_worktree_ports
    from .worktree import get_worktree_info

    meta = load_snapshot_meta(task_id)
    if not meta:
        return None

    info = meta.to_dict()
    worktree_info = get_worktree_info(task_id, meta.project_id)
    info["worktree_exists"] = str(worktree_info is not None).lower()
    if worktree_info:
        info["worktree_branch"] = worktree_info.branch

    ports = get_worktree_ports(task_id, meta.project_id)
    if ports:
        info["backend_port"] = ports.backend_port
        info["frontend_port"] = ports.frontend_port
        info["api_url"] = ports.api_url
        info["frontend_url"] = ports.frontend_url

    return info


def _checkpoint_is_active(checkpoint: SnapshotMeta) -> bool:
    """Return True when checkpoint metadata still has a live worktree or branch."""
    from .worktree import get_worktree_info

    if checkpoint.worktree_path and get_worktree_info(checkpoint.task_id, checkpoint.project_id) is not None:
        return True
    return bool(get_task_branches(checkpoint.task_id, project_id=checkpoint.project_id))


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
