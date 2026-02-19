"""Worktree management for CLI task isolation.

Each claimed task gets an isolated worktree at:
    ~/.local/share/st/worktrees/<project-id>/<task-id>/
Branch naming: <task-id>/main
"""
from __future__ import annotations

import contextlib
import shutil
from dataclasses import dataclass
from pathlib import Path

from .worktree_deps import symlink_gitignored_deps
from .worktree_git import WorktreeError, get_branch_name, get_current_branch, get_repo_root, run_git
from .worktree_ops import (
    create_worktree_branch,
    detect_base_branch,
    get_project_cwd,
    get_worktree_branch,
    verify_base_branch,
)
from .worktree_paths import get_worktree_path, get_worktrees_base_dir


@dataclass
class WorktreeInfo:
    """Information about a task's worktree."""
    path: Path
    branch: str
    task_id: str
    base_branch: str
    is_active: bool = True
    project_id: str | None = None


def create_worktree(task_id: str, base_branch: str = "main", project_id: str | None = None) -> WorktreeInfo:
    """Create a worktree for a task."""
    worktree_path = get_worktree_path(task_id, project_id)
    branch_name = get_branch_name(task_id)
    if worktree_path.exists():
        existing_info = get_worktree_info(task_id, project_id)
        if existing_info:
            return existing_info
        shutil.rmtree(worktree_path)
    repo_root = get_repo_root(cwd=get_project_cwd(project_id))
    verify_base_branch(base_branch, repo_root)
    create_worktree_branch(worktree_path, branch_name, base_branch, repo_root, task_id)
    symlink_gitignored_deps(repo_root, worktree_path)
    return WorktreeInfo(path=worktree_path, branch=branch_name, task_id=task_id,
                        base_branch=base_branch, is_active=True, project_id=project_id)


def get_worktree_info(task_id: str, project_id: str | None = None) -> WorktreeInfo | None:
    """Get information about an existing worktree."""
    worktree_path = get_worktree_path(task_id, project_id)
    if not worktree_path.exists() or not (worktree_path / ".git").exists():
        return None
    branch = get_worktree_branch(worktree_path)
    if not branch:
        return None
    return WorktreeInfo(path=worktree_path, branch=branch, task_id=task_id,
                        base_branch=detect_base_branch(worktree_path), is_active=True, project_id=project_id)


def _resolve_repo_root(worktree_path: Path) -> Path | None:
    """Return repo root, or None after cleaning up an orphaned worktree directory."""
    try:
        return get_repo_root()
    except WorktreeError:
        pass
    try:
        return get_repo_root(worktree_path)
    except WorktreeError:
        shutil.rmtree(worktree_path)
    return None


def _force_remove_worktree(worktree_path: Path, repo_root: Path) -> None:
    """Remove worktree via git, falling back to direct removal on failure."""
    try:
        run_git(["worktree", "remove", str(worktree_path), "--force"], cwd=repo_root)
        return
    except WorktreeError:
        pass
    try:
        shutil.rmtree(worktree_path)
        run_git(["worktree", "prune"], cwd=repo_root, check=False)
    except OSError as e:
        raise WorktreeError(f"Failed to remove worktree directory: {e}") from e


def remove_worktree(task_id: str, delete_branch: bool = True, project_id: str | None = None) -> bool:
    """Remove a task's worktree and optionally its branch."""
    worktree_path = get_worktree_path(task_id, project_id)
    branch_name = get_branch_name(task_id)
    if not worktree_path.exists():
        return False
    repo_root = _resolve_repo_root(worktree_path)
    if repo_root is None:
        return True
    _force_remove_worktree(worktree_path, repo_root)
    if delete_branch:
        with contextlib.suppress(WorktreeError):
            run_git(["branch", "-D", branch_name], cwd=repo_root, check=False)
    return True


def _worktrees_for_dir(base_dir: Path, project_id: str) -> list[WorktreeInfo]:
    """Collect valid WorktreeInfo entries from a project base directory."""
    return [info for entry in base_dir.iterdir() if entry.is_dir()
            for info in [get_worktree_info(entry.name, project_id)] if info]

def get_active_worktrees(project_id: str | None = None) -> list[WorktreeInfo]:
    """List all active worktrees."""
    if project_id:
        base_dir = get_worktrees_base_dir(project_id)
        return _worktrees_for_dir(base_dir, project_id) if base_dir.exists() else []
    base_dir = get_worktrees_base_dir()
    if not base_dir.exists():
        return []
    worktrees: list[WorktreeInfo] = []
    for proj_entry in (e for e in base_dir.iterdir() if e.is_dir()):
        worktrees.extend(_worktrees_for_dir(proj_entry, proj_entry.name))
    return worktrees


def check_worktree_safety(cwd: Path | None = None, project_id: str | None = None) -> tuple[bool, str | None]:
    """Check if it's safe to commit on main."""
    current_branch = get_current_branch(cwd)
    if current_branch is None or current_branch not in ("main", "master"):
        return (True, None)
    active_worktrees = get_active_worktrees(project_id)
    if not active_worktrees:
        return (True, None)
    wt_lines = "\n".join(f"  - Task: {wt.task_id}\n    Branch: {wt.branch}\n    Path: {wt.path}"
                         for wt in active_worktrees)
    footer = ("\nThis usually means you should be working in one of these worktrees"
              "\ninstead of committing directly to the main branch.\n\nOptions:"
              "\n  1. Switch to a worktree: cd <worktree-path>"
              "\n  2. Create a new task: sf task create <task-name>"
              "\n  3. Bypass this check: git commit --no-verify")
    msg = (f"WARNING: You are on '{current_branch}' with {len(active_worktrees)} active worktree(s)."
           f"\n\nActive worktrees:\n{wt_lines}{footer}")
    return (False, msg)


# Re-export for backward compatibility
__all__ = [
    "WorktreeError", "WorktreeInfo", "check_worktree_safety", "create_worktree",
    "get_active_worktrees", "get_current_branch", "get_worktree_info",
    "get_worktree_path", "get_worktrees_base_dir", "remove_worktree",
]
