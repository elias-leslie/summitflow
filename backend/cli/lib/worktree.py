"""Worktree management for CLI task isolation.

Provides git worktree operations for st claim workflow.
Each claimed task gets an isolated worktree at:
    ~/.summitflow/worktrees/<task-id>/

With the existing branch naming:
    <task-id>/main
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class WorktreeError(Exception):
    """Error during worktree operations."""

    pass


@dataclass
class WorktreeInfo:
    """Information about a task's worktree."""

    path: Path
    branch: str
    task_id: str
    base_branch: str
    is_active: bool = True


def get_worktrees_base_dir() -> Path:
    """Returns ~/.summitflow/worktrees directory.

    Creates the directory if it doesn't exist.
    """
    base_dir = Path.home() / ".summitflow" / "worktrees"
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir


def get_worktree_path(task_id: str) -> Path:
    """Returns the path for a specific task's worktree.

    Args:
        task_id: The task identifier.

    Returns:
        Path to the worktree directory.
    """
    sanitized = _sanitize_task_id(task_id)
    return get_worktrees_base_dir() / sanitized


def _sanitize_task_id(task_id: str) -> str:
    """Sanitize task ID for safe use in file paths.

    Args:
        task_id: The raw task identifier.

    Returns:
        Sanitized task ID safe for paths.
    """
    # Replace any characters that aren't alphanumeric, dash, or underscore
    sanitized = re.sub(r"[^a-zA-Z0-9_-]", "_", task_id)
    # Remove leading/trailing underscores and collapse multiple underscores
    sanitized = re.sub(r"_+", "_", sanitized).strip("_")
    # Ensure we have something
    if not sanitized:
        sanitized = "task"
    return sanitized


def _run_git(
    args: list[str], cwd: Path | None = None, check: bool = True
) -> subprocess.CompletedProcess:
    """Run a git command.

    Args:
        args: Git command arguments (without 'git' prefix).
        cwd: Working directory for the command.
        check: Whether to raise on non-zero exit code.

    Returns:
        CompletedProcess with command results.

    Raises:
        WorktreeError: If command fails and check is True.
    """
    cmd = ["git"] + args
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=check,
        )
        return result
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.strip() if e.stderr else str(e)
        raise WorktreeError(f"Git command failed: {' '.join(cmd)}\n{stderr}") from e


def _get_repo_root(cwd: Path | None = None) -> Path:
    """Get the root of the current git repository.

    Args:
        cwd: Working directory to start from.

    Returns:
        Path to the repository root.

    Raises:
        WorktreeError: If not in a git repository.
    """
    result = _run_git(["rev-parse", "--show-toplevel"], cwd=cwd)
    return Path(result.stdout.strip())


def _get_branch_name(task_id: str) -> str:
    """Get the branch name for a task.

    Args:
        task_id: The task identifier.

    Returns:
        Branch name in format: <task-id>/main
    """
    return f"{task_id}/main"


def create_worktree(task_id: str, base_branch: str = "main") -> WorktreeInfo:
    """Create a worktree for a task.

    Args:
        task_id: The task identifier.
        base_branch: The branch to base the worktree on.

    Returns:
        WorktreeInfo with details about the created worktree.

    Raises:
        WorktreeError: If worktree creation fails.
    """
    worktree_path = get_worktree_path(task_id)
    branch_name = _get_branch_name(task_id)

    # Check if worktree already exists
    if worktree_path.exists():
        existing_info = get_worktree_info(task_id)
        if existing_info:
            return existing_info
        # Directory exists but not a valid worktree, clean it up
        shutil.rmtree(worktree_path)

    # Get repo root to run git commands from
    repo_root = _get_repo_root()

    # Ensure base branch exists and is up to date
    try:
        _run_git(["rev-parse", "--verify", base_branch], cwd=repo_root)
    except WorktreeError:
        raise WorktreeError(f"Base branch '{base_branch}' does not exist")

    # Create the worktree with a new branch
    try:
        _run_git(
            ["worktree", "add", str(worktree_path), "-b", branch_name, base_branch],
            cwd=repo_root,
        )
    except WorktreeError as e:
        # Branch might already exist, try without -b
        if "already exists" in str(e):
            try:
                _run_git(
                    ["worktree", "add", str(worktree_path), branch_name],
                    cwd=repo_root,
                )
            except WorktreeError:
                raise WorktreeError(
                    f"Failed to create worktree for task '{task_id}': {e}"
                )
        else:
            raise

    return WorktreeInfo(
        path=worktree_path,
        branch=branch_name,
        task_id=task_id,
        base_branch=base_branch,
        is_active=True,
    )


def get_worktree_info(task_id: str) -> WorktreeInfo | None:
    """Get information about an existing worktree.

    Args:
        task_id: The task identifier.

    Returns:
        WorktreeInfo if worktree exists, None otherwise.
    """
    worktree_path = get_worktree_path(task_id)

    if not worktree_path.exists():
        return None

    # Verify it's a valid git worktree
    git_dir = worktree_path / ".git"
    if not git_dir.exists():
        return None

    # Get current branch
    try:
        result = _run_git(
            ["rev-parse", "--abbrev-ref", "HEAD"], cwd=worktree_path, check=False
        )
        if result.returncode != 0:
            return None
        branch = result.stdout.strip()
    except (WorktreeError, OSError):
        return None

    # Try to determine base branch from reflog or merge-base
    base_branch = "main"  # Default assumption
    try:
        # Check common base branches
        for candidate in ["main", "master", "develop"]:
            result = _run_git(
                ["rev-parse", "--verify", f"origin/{candidate}"],
                cwd=worktree_path,
                check=False,
            )
            if result.returncode == 0:
                base_branch = candidate
                break
    except (WorktreeError, OSError):
        pass

    return WorktreeInfo(
        path=worktree_path,
        branch=branch,
        task_id=task_id,
        base_branch=base_branch,
        is_active=True,
    )


def remove_worktree(task_id: str, delete_branch: bool = True) -> bool:
    """Remove a task's worktree and optionally its branch.

    Args:
        task_id: The task identifier.
        delete_branch: Whether to also delete the associated branch.

    Returns:
        True if worktree was removed, False if it didn't exist.

    Raises:
        WorktreeError: If removal fails.
    """
    worktree_path = get_worktree_path(task_id)
    branch_name = _get_branch_name(task_id)

    if not worktree_path.exists():
        return False

    # Get repo root before removing worktree
    try:
        repo_root = _get_repo_root()
    except WorktreeError:
        # Try to find repo root from worktree itself
        try:
            repo_root = _get_repo_root(worktree_path)
        except WorktreeError:
            # Can't find repo, just remove the directory
            shutil.rmtree(worktree_path)
            return True

    # Remove the worktree using git
    try:
        _run_git(["worktree", "remove", str(worktree_path), "--force"], cwd=repo_root)
    except WorktreeError:
        # Force removal if git worktree remove fails
        try:
            shutil.rmtree(worktree_path)
            # Prune stale worktree entries
            _run_git(["worktree", "prune"], cwd=repo_root, check=False)
        except OSError as e:
            raise WorktreeError(f"Failed to remove worktree directory: {e}")

    # Delete the branch if requested
    if delete_branch:
        try:
            _run_git(["branch", "-D", branch_name], cwd=repo_root, check=False)
        except WorktreeError:
            # Branch deletion is best-effort
            pass

    return True


def get_active_worktrees() -> list[WorktreeInfo]:
    """List all active worktrees in the summitflow directory.

    Returns:
        List of WorktreeInfo for each active worktree.
    """
    base_dir = get_worktrees_base_dir()
    worktrees: list[WorktreeInfo] = []

    if not base_dir.exists():
        return worktrees

    for entry in base_dir.iterdir():
        if entry.is_dir():
            # Extract task_id from directory name
            task_id = entry.name
            info = get_worktree_info(task_id)
            if info:
                worktrees.append(info)

    return worktrees


def get_current_branch(cwd: Path | None = None) -> str | None:
    """Get the current branch name.

    Args:
        cwd: Working directory to check. If None, uses current directory.

    Returns:
        Current branch name, or None if not in a git repo or detached HEAD.
    """
    try:
        result = _run_git(
            ["symbolic-ref", "--short", "HEAD"], cwd=cwd, check=False
        )
        if result.returncode == 0:
            return result.stdout.strip()
        return None
    except (WorktreeError, OSError):
        return None


def check_worktree_safety(cwd: Path | None = None) -> tuple[bool, str | None]:
    """Check if it's safe to commit on main.

    Detects when someone is about to commit on main/master while having
    active worktrees, which usually indicates they should be working in
    a worktree instead.

    Args:
        cwd: Working directory to check. If None, uses current directory.

    Returns:
        Tuple of (is_safe, warning_message).
        - is_safe: True if safe to proceed, False if suspicious state detected.
        - warning_message: Detailed warning if not safe, None otherwise.
    """
    # Get current branch
    current_branch = get_current_branch(cwd)
    if current_branch is None:
        # Not in a git repo or detached HEAD - allow
        return (True, None)

    # Only check for main/master branches
    if current_branch not in ("main", "master"):
        return (True, None)

    # Check for active worktrees
    active_worktrees = get_active_worktrees()
    if not active_worktrees:
        # No active worktrees - still on main, but no task isolation in use
        return (True, None)

    # Suspicious state: on main/master with active worktrees
    lines = [
        f"WARNING: You are on '{current_branch}' with {len(active_worktrees)} active worktree(s).",
        "",
        "Active worktrees:",
    ]

    for wt in active_worktrees:
        lines.append(f"  - Task: {wt.task_id}")
        lines.append(f"    Branch: {wt.branch}")
        lines.append(f"    Path: {wt.path}")

    lines.extend([
        "",
        "This usually means you should be working in one of these worktrees",
        "instead of committing directly to the main branch.",
        "",
        "Options:",
        "  1. Switch to a worktree: cd <worktree-path>",
        "  2. Create a new task: sf task create <task-name>",
        "  3. Bypass this check: git commit --no-verify",
    ])

    return (False, "\n".join(lines))
