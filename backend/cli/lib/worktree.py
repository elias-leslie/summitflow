"""Worktree management for CLI task isolation.

Isolated lanes live at `/srv/workspaces/lanes/<project-id>/<task-id>/` when the
shared Btrfs workspace is available, otherwise they fall back to
`~/.local/share/st/worktrees/<project-id>/<task-id>/`.
Branch naming: <task-id>/main
"""

from __future__ import annotations

import contextlib
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.storage.tasks import canonicalize_task_id

from .worktree_deps import symlink_gitignored_deps
from .worktree_git import WorktreeError, get_branch_name, get_current_branch, get_repo_root, run_git
from .worktree_helpers import (
    build_safety_warning,
    collect_all_worktrees,
    force_remove_worktree,
    resolve_repo_root,
    worktrees_for_dir,
)
from .worktree_ops import (
    create_worktree_branch,
    detect_base_branch,
    get_project_cwd,
    get_worktree_branch,
    verify_base_branch,
)
from .worktree_paths import (
    get_lanes_base_dir,
    get_worktree_path,
    get_worktrees_base_dir,
    workspaces_root_available,
)


@dataclass
class WorktreeInfo:
    """Information about a task's worktree."""

    path: Path
    branch: str
    task_id: str
    base_branch: str
    is_active: bool = True
    project_id: str | None = None


def _run_btrfs(args: list[str]) -> None:
    """Run a Btrfs command and normalize failures to WorktreeError."""
    try:
        subprocess.run(
            ["btrfs", *args],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip() or str(exc)
        raise WorktreeError(f"Btrfs command failed: btrfs {' '.join(args)}\n{stderr}") from exc
    except OSError as exc:
        raise WorktreeError(f"Failed to run btrfs {' '.join(args)}: {exc}") from exc


def _is_btrfs_lane_path(path: Path, project_id: str | None) -> bool:
    """Return True when the worktree path should be managed as a Btrfs lane."""
    if not project_id or not workspaces_root_available():
        return False
    lanes_base = get_lanes_base_dir(project_id).resolve()
    try:
        relative = path.resolve().relative_to(lanes_base)
    except ValueError:
        return False
    return len(relative.parts) == 1


def _remove_worktree_path(path: Path) -> None:
    """Remove a stale worktree path, preferring Btrfs subvolume deletion."""
    if not path.exists():
        return
    with contextlib.suppress(WorktreeError):
        _run_btrfs(["subvolume", "delete", str(path)])
    if path.exists():
        shutil.rmtree(path)


def _prepare_worktree_path(worktree_path: Path, project_id: str | None) -> bool:
    """Pre-create a Btrfs lane subvolume when the shared workspace is active."""
    if not _is_btrfs_lane_path(worktree_path, project_id):
        return False
    worktree_path.parent.mkdir(parents=True, exist_ok=True)
    _run_btrfs(["subvolume", "create", str(worktree_path)])
    return True


def create_worktree(
    task_id: str, base_branch: str = "main", project_id: str | None = None
) -> WorktreeInfo:
    """Create a worktree for a task."""
    task_id = canonicalize_task_id(task_id)
    worktree_path = get_worktree_path(task_id, project_id)
    branch_name = get_branch_name(task_id)
    if worktree_path.exists():
        existing_info = get_worktree_info(task_id, project_id)
        if existing_info:
            return existing_info
        _remove_worktree_path(worktree_path)
    repo_root = get_repo_root(cwd=get_project_cwd(project_id))
    verify_base_branch(base_branch, repo_root)
    created_subvolume = _prepare_worktree_path(worktree_path, project_id)
    try:
        create_worktree_branch(worktree_path, branch_name, base_branch, repo_root, task_id)
    except Exception:
        if created_subvolume:
            with contextlib.suppress(WorktreeError):
                _remove_worktree_path(worktree_path)
        raise
    symlink_gitignored_deps(repo_root, worktree_path)
    return WorktreeInfo(
        path=worktree_path,
        branch=branch_name,
        task_id=task_id,
        base_branch=base_branch,
        is_active=True,
        project_id=project_id,
    )


def get_worktree_info(task_id: str, project_id: str | None = None) -> WorktreeInfo | None:
    """Get information about an existing worktree."""
    task_id = canonicalize_task_id(task_id)
    worktree_path = get_worktree_path(task_id, project_id)
    if not worktree_path.exists() or not (worktree_path / ".git").exists():
        return None
    branch = get_worktree_branch(worktree_path)
    if not branch:
        return None
    return WorktreeInfo(
        path=worktree_path,
        branch=branch,
        task_id=task_id,
        base_branch=detect_base_branch(worktree_path),
        is_active=True,
        project_id=project_id,
    )


def remove_worktree(
    task_id: str, delete_branch: bool = True, project_id: str | None = None
) -> bool:
    """Remove a task's worktree and optionally its branch."""
    task_id = canonicalize_task_id(task_id)
    worktree_path = get_worktree_path(task_id, project_id)
    branch_name = get_branch_name(task_id)
    if not worktree_path.exists():
        return False
    repo_root = resolve_repo_root(worktree_path)
    if repo_root is None:
        return True
    force_remove_worktree(worktree_path, repo_root)
    if delete_branch:
        with contextlib.suppress(WorktreeError):
            run_git(["branch", "-D", branch_name], cwd=repo_root, check=False)
    return True


def get_active_worktrees(project_id: str | None = None) -> list[WorktreeInfo]:
    """List all active worktrees."""
    if project_id:
        base_dir = get_worktrees_base_dir(project_id)
        if not base_dir.exists():
            return []
        return worktrees_for_dir(base_dir, get_worktree_info, project_id)
    return collect_all_worktrees(get_worktree_info)


def check_worktree_safety(
    cwd: Path | None = None, project_id: str | None = None
) -> tuple[bool, str | None]:
    """Check if it's safe to commit on main."""
    current_branch = get_current_branch(cwd)
    if current_branch is None or current_branch not in ("main", "master"):
        return (True, None)
    active_worktrees = get_active_worktrees(project_id)
    if not active_worktrees:
        return (True, None)
    return (False, build_safety_warning(current_branch, active_worktrees))


# Re-export for backward compatibility
__all__ = [
    "WorktreeError",
    "WorktreeInfo",
    "check_worktree_safety",
    "create_worktree",
    "get_active_worktrees",
    "get_current_branch",
    "get_worktree_info",
    "get_worktree_path",
    "get_worktrees_base_dir",
    "remove_worktree",
]
