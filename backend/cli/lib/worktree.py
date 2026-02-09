"""Worktree management for CLI task isolation.

Provides git worktree operations for st claim workflow.
Each claimed task gets an isolated worktree at:
    ~/.local/share/st/worktrees/<project-id>/<task-id>/

With the existing branch naming:
    <task-id>/main
"""

from __future__ import annotations

import contextlib
import shutil
from dataclasses import dataclass
from pathlib import Path

from .worktree_deps import symlink_gitignored_deps
from .worktree_git import (
    WorktreeError,
    get_branch_name,
    get_current_branch,
    get_repo_root,
    run_git,
)
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


def create_worktree(
    task_id: str, base_branch: str = "main", project_id: str | None = None
) -> WorktreeInfo:
    """Create a worktree for a task."""
    worktree_path = get_worktree_path(task_id, project_id)
    branch_name = get_branch_name(task_id)

    # Check if worktree already exists
    if worktree_path.exists():
        existing_info = get_worktree_info(task_id, project_id)
        if existing_info:
            return existing_info
        shutil.rmtree(worktree_path)

    # Get repo root for the target project
    project_cwd = get_project_cwd(project_id)
    repo_root = get_repo_root(cwd=project_cwd)

    # Verify base branch exists
    verify_base_branch(base_branch, repo_root)

    # Create the worktree with a new branch
    create_worktree_branch(worktree_path, branch_name, base_branch, repo_root, task_id)

    # Symlink dependencies
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
    worktree_path = get_worktree_path(task_id, project_id)

    if not worktree_path.exists():
        return None

    # Verify it's a valid git worktree
    git_dir = worktree_path / ".git"
    if not git_dir.exists():
        return None

    # Get current branch
    branch = get_worktree_branch(worktree_path)
    if not branch:
        return None

    # Detect base branch
    base_branch = detect_base_branch(worktree_path)

    return WorktreeInfo(
        path=worktree_path,
        branch=branch,
        task_id=task_id,
        base_branch=base_branch,
        is_active=True,
        project_id=project_id,
    )


def remove_worktree(
    task_id: str, delete_branch: bool = True, project_id: str | None = None
) -> bool:
    """Remove a task's worktree and optionally its branch."""
    worktree_path = get_worktree_path(task_id, project_id)
    branch_name = get_branch_name(task_id)

    if not worktree_path.exists():
        return False

    # Get repo root before removing worktree
    try:
        repo_root = get_repo_root()
    except WorktreeError:
        try:
            repo_root = get_repo_root(worktree_path)
        except WorktreeError:
            shutil.rmtree(worktree_path)
            return True

    # Remove the worktree using git
    try:
        run_git(["worktree", "remove", str(worktree_path), "--force"], cwd=repo_root)
    except WorktreeError:
        try:
            shutil.rmtree(worktree_path)
            run_git(["worktree", "prune"], cwd=repo_root, check=False)
        except OSError as e:
            raise WorktreeError(f"Failed to remove worktree directory: {e}") from e

    # Delete the branch if requested
    if delete_branch:
        with contextlib.suppress(WorktreeError):
            run_git(["branch", "-D", branch_name], cwd=repo_root, check=False)

    return True


def get_active_worktrees(project_id: str | None = None) -> list[WorktreeInfo]:
    """List all active worktrees."""
    worktrees: list[WorktreeInfo] = []

    if project_id:
        base_dir = get_worktrees_base_dir(project_id)
        if not base_dir.exists():
            return worktrees

        for entry in base_dir.iterdir():
            if entry.is_dir():
                info = get_worktree_info(entry.name, project_id)
                if info:
                    worktrees.append(info)
    else:
        base_dir = get_worktrees_base_dir()
        if not base_dir.exists():
            return worktrees

        for project_entry in base_dir.iterdir():
            if project_entry.is_dir():
                proj_id = project_entry.name
                for task_entry in project_entry.iterdir():
                    if task_entry.is_dir():
                        info = get_worktree_info(task_entry.name, proj_id)
                        if info:
                            worktrees.append(info)

    return worktrees


def check_worktree_safety(
    cwd: Path | None = None, project_id: str | None = None
) -> tuple[bool, str | None]:
    """Check if it's safe to commit on main."""
    current_branch = get_current_branch(cwd)
    if current_branch is None:
        return (True, None)

    if current_branch not in ("main", "master"):
        return (True, None)

    active_worktrees = get_active_worktrees(project_id)
    if not active_worktrees:
        return (True, None)

    # Build warning message
    lines = [
        f"WARNING: You are on '{current_branch}' with {len(active_worktrees)} active worktree(s).",
        "",
        "Active worktrees:",
    ]

    for wt in active_worktrees:
        lines.append(f"  - Task: {wt.task_id}")
        lines.append(f"    Branch: {wt.branch}")
        lines.append(f"    Path: {wt.path}")

    lines.extend(
        [
            "",
            "This usually means you should be working in one of these worktrees",
            "instead of committing directly to the main branch.",
            "",
            "Options:",
            "  1. Switch to a worktree: cd <worktree-path>",
            "  2. Create a new task: sf task create <task-name>",
            "  3. Bypass this check: git commit --no-verify",
        ]
    )

    return (False, "\n".join(lines))


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
