"""Core git helpers for CLI checkout and branch flows."""

from __future__ import annotations

import subprocess
from pathlib import Path


class RepoGitError(Exception):
    """Error during repo git operations."""

    pass


def run_git(
    args: list[str], cwd: Path | None = None, check: bool = True
) -> subprocess.CompletedProcess[str]:
    """Run a git command.

    Args:
        args: Git command arguments (without 'git' prefix).
        cwd: Working directory for the command.
        check: Whether to raise on non-zero exit code.

    Returns:
        CompletedProcess with command results.

    Raises:
        RepoGitError: If command fails and check is True.
    """
    cmd = ["git", *args]
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
        raise RepoGitError(f"Git command failed: {' '.join(cmd)}\n{stderr}") from e


def get_repo_root(cwd: Path | None = None) -> Path:
    """Get the root of the current git repository.

    Args:
        cwd: Working directory to start from.

    Returns:
        Path to the repository root.

    Raises:
        RepoGitError: If not in a git repository.
    """
    result = run_git(["rev-parse", "--show-toplevel"], cwd=cwd)
    return Path(result.stdout.strip())


def get_branch_name(task_id: str) -> str:
    """Get the branch name for a task.

    Args:
        task_id: The task identifier.

    Returns:
        Branch name in format: <task-id>/main
    """
    return f"{task_id}/main"


def get_current_branch(cwd: Path | None = None) -> str | None:
    """Get the current branch name.

    Args:
        cwd: Working directory to check. If None, uses current directory.

    Returns:
        Current branch name, or None if not in a git repo or detached HEAD.
    """
    try:
        result = run_git(["symbolic-ref", "--short", "HEAD"], cwd=cwd, check=False)
        if result.returncode == 0:
            return result.stdout.strip()
        return None
    except (RepoGitError, OSError):
        return None
