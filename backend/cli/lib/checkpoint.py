"""Checkpoint library for st CLI.

Provides worktree isolation for safe task execution.
Used by st claim, st done, st abandon, and st checkpoints commands.

Worktree paths are per-project at:
    ~/.local/share/st/worktrees/<project-id>/<task-id>/
"""

from __future__ import annotations

import contextlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from .checkpoint_branches import (
    create_subtask_branch,
    delete_subtask_branch,
    delete_task_branches,
    merge_subtask_branch,
    merge_task_branch,
)
from .checkpoint_metadata import (
    SnapshotMeta,
    get_claimed_by,
    get_current_branch,
    get_meta_path,
    get_snapshots_dir,
    is_working_tree_clean,
    load_snapshot_meta,
    save_snapshot_meta,
)

# Re-export for backwards compatibility
__all__ = [
    "SnapshotMeta",
    "create_subtask_branch",
    "create_task_snapshot",
    "delete_subtask_branch",
    "delete_task_branches",
    "get_active_checkpoints",
    "get_snapshot_info",
    "has_active_task",
    "merge_subtask_branch",
    "merge_task_branch",
    "remove_snapshot",
]


def create_task_snapshot(task_id: str, project_id: str, use_worktree: bool = True) -> SnapshotMeta:
    """Create worktree checkpoint for task.

    Creates metadata file and isolated git worktree.
    The worktree provides code isolation at ~/.local/share/st/worktrees/<project-id>/<task-id>/.
    Also allocates isolated ports for worktree services (backend/frontend).

    Args:
        task_id: Task identifier
        project_id: Project identifier
        use_worktree: Whether to create isolated worktree (default True)

    Returns:
        SnapshotMeta with checkpoint details including worktree path and ports

    Raises:
        SystemExit: On git errors
    """
    from .port_manager import allocate_ports
    from .worktree import WorktreeError, create_worktree

    meta_path = get_meta_path(task_id)
    base_branch = get_current_branch()

    # Check for existing checkpoint
    if meta_path.exists():
        print(f"Error: Checkpoint already exists for {task_id}", file=sys.stderr)
        print("Use 'st abandon' to remove existing checkpoint first.", file=sys.stderr)
        sys.exit(1)

    worktree_path: str | None = None
    backend_port: int | None = None
    frontend_port: int | None = None

    if use_worktree:
        # Create isolated worktree for task
        try:
            worktree_info = create_worktree(task_id, base_branch, project_id)
            worktree_path = str(worktree_info.path)
            print(f"Created worktree: {worktree_path}")

            # Allocate isolated ports for worktree services
            ports = allocate_ports(task_id)
            backend_port = ports.backend_port
            frontend_port = ports.frontend_port
            print(f"Allocated ports: backend={backend_port}, frontend={frontend_port}")
        except WorktreeError as e:
            print(f"Error: Failed to create worktree: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        # Legacy mode: create branch in main repo
        task_branch = f"{task_id}/main"
        try:
            subprocess.run(
                ["git", "checkout", "-b", task_branch],
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as e:
            print(f"Error: Failed to create git branch: {e.stderr}", file=sys.stderr)
            sys.exit(1)

    # Create metadata
    meta = SnapshotMeta(
        task_id=task_id,
        project_id=project_id,
        base_branch=base_branch,
        created_at=datetime.now(UTC).isoformat(),
        claimed_by=get_claimed_by(),
        worktree_path=worktree_path,
        backend_port=backend_port,
        frontend_port=frontend_port,
    )
    save_snapshot_meta(meta)

    return meta


def remove_snapshot(
    task_id: str, remove_worktree: bool = True, project_id: str | None = None
) -> bool:
    """Delete checkpoint metadata and optionally worktree after completion.

    Args:
        task_id: Task identifier
        remove_worktree: Whether to also remove the worktree (default True)
        project_id: Project identifier for per-project worktree paths

    Returns:
        True on success
    """
    from .worktree import remove_worktree as rm_worktree

    meta_path = get_meta_path(task_id)

    # Load project_id from meta if not provided
    if project_id is None:
        meta = load_snapshot_meta(task_id)
        if meta:
            project_id = meta.project_id

    # Remove worktree if it exists (best-effort cleanup)
    if remove_worktree:
        with contextlib.suppress(Exception):
            rm_worktree(task_id, delete_branch=False, project_id=project_id)

    meta_path.unlink(missing_ok=True)

    return True


def get_active_checkpoints(project_id: str | None = None) -> list[SnapshotMeta]:
    """List all active checkpoints.

    Args:
        project_id: Optional filter by project

    Returns:
        List of SnapshotMeta for active checkpoints
    """
    snapshots_dir = Path.cwd() / ".st" / "snapshots"
    if not snapshots_dir.exists():
        return []

    checkpoints = []
    for meta_file in snapshots_dir.glob("*.meta.json"):
        try:
            meta = SnapshotMeta.from_dict(json.loads(meta_file.read_text()))
            if project_id is None or meta.project_id == project_id:
                checkpoints.append(meta)
        except (json.JSONDecodeError, KeyError):
            continue

    # Sort by creation time, newest first
    checkpoints.sort(key=lambda m: m.created_at, reverse=True)
    return checkpoints


def has_active_task(project_id: str) -> str | None:
    """Check if a task is already claimed for a project.

    Returns the task_id if one exists, else None.
    """
    checkpoints = get_active_checkpoints(project_id)
    return checkpoints[0].task_id if checkpoints else None


def get_snapshot_info(task_id: str) -> dict[str, str | int | None] | None:
    """Get checkpoint info for a task.

    Returns dict with checkpoint details or None if not found.
    Includes worktree_path, worktree_exists for isolation status,
    and allocated ports for worktree services.
    """
    from .port_manager import get_worktree_ports
    from .worktree import get_worktree_info

    meta = load_snapshot_meta(task_id)
    if not meta:
        return None

    info = meta.to_dict()

    # Check worktree status (use project_id from meta)
    worktree_info = get_worktree_info(task_id, meta.project_id)
    info["worktree_exists"] = str(worktree_info is not None).lower()
    if worktree_info:
        info["worktree_branch"] = worktree_info.branch

    # Add port info (from ports.json or meta)
    ports = get_worktree_ports(task_id)
    if ports:
        info["backend_port"] = ports.backend_port
        info["frontend_port"] = ports.frontend_port
        info["api_url"] = ports.api_url
        info["frontend_url"] = ports.frontend_url

    return info
