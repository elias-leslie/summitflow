"""Private helper functions for worktree management.

Not part of the public API; imported only by worktree.py.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from .worktree_git import WorktreeError, get_repo_root, run_git
from .worktree_paths import get_worktrees_base_dir


def resolve_repo_root(worktree_path: Path) -> Path | None:
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


def force_remove_worktree(worktree_path: Path, repo_root: Path) -> None:
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


def worktrees_for_dir(base_dir: Path, get_info_fn, project_id: str) -> list:
    """Collect valid worktree info entries from a project base directory."""
    return [
        info
        for entry in base_dir.iterdir()
        if entry.is_dir()
        for info in [get_info_fn(entry.name, project_id)]
        if info
    ]


def collect_all_worktrees(get_info_fn) -> list:
    """Collect all worktrees across all projects."""
    base_dir = get_worktrees_base_dir()
    if not base_dir.exists():
        return []
    worktrees = []
    for proj_entry in (e for e in base_dir.iterdir() if e.is_dir()):
        worktrees.extend(worktrees_for_dir(proj_entry, get_info_fn, proj_entry.name))
    return worktrees


_SAFETY_FOOTER = (
    "\nThis usually means you should be working in one of these worktrees"
    "\ninstead of committing directly to the main branch.\n\nOptions:"
    "\n  1. Switch to a worktree: cd <worktree-path>"
    "\n  2. Create a new task: sf task create <task-name>"
    "\n  3. Bypass this check: git commit --no-verify"
)


def build_safety_warning(current_branch: str, active_worktrees: list) -> str:
    """Build the safety warning message."""
    wt_lines = "\n".join(
        f"  - Task: {wt.task_id}\n    Branch: {wt.branch}\n    Path: {wt.path}"
        for wt in active_worktrees
    )
    return (
        f"WARNING: You are on '{current_branch}' with {len(active_worktrees)} active worktree(s)."
        f"\n\nActive worktrees:\n{wt_lines}{_SAFETY_FOOTER}"
    )
