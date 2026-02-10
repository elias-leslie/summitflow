"""Git operations for cleanup commands."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path


def run_git(
    args: list[str], cwd: Path | None = None, check: bool = True
) -> subprocess.CompletedProcess[str]:
    """Run a git command."""
    cmd = ["git", *args]
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=check,
    )


def get_repo_root() -> Path | None:
    """Get the main repository root."""
    try:
        result = run_git(["rev-parse", "--show-toplevel"])
        return Path(result.stdout.strip())
    except subprocess.CalledProcessError:
        return None


def get_commits_ahead_behind(worktree_path: Path, base_branch: str = "main") -> tuple[int, int]:
    """Get number of commits ahead and behind base branch."""
    try:
        # Fetch to ensure we have latest refs
        run_git(["fetch", "origin", base_branch], cwd=worktree_path, check=False)

        # Get commits ahead (in worktree but not in origin/base)
        result = run_git(
            ["rev-list", "--count", f"origin/{base_branch}..HEAD"],
            cwd=worktree_path,
            check=False,
        )
        ahead = int(result.stdout.strip()) if result.returncode == 0 else 0

        # Get commits behind (in origin/base but not in worktree)
        result = run_git(
            ["rev-list", "--count", f"HEAD..origin/{base_branch}"],
            cwd=worktree_path,
            check=False,
        )
        behind = int(result.stdout.strip()) if result.returncode == 0 else 0

        return ahead, behind
    except (subprocess.CalledProcessError, ValueError):
        return 0, 0


def has_merge_conflicts(worktree_path: Path, base_branch: str = "main") -> bool:
    """Check if merging base branch would cause conflicts."""
    try:
        # Get current HEAD
        head_result = run_git(["rev-parse", "HEAD"], cwd=worktree_path, check=False)
        if head_result.returncode != 0:
            return False
        head = head_result.stdout.strip()

        # Get base branch ref
        base_result = run_git(
            ["rev-parse", f"origin/{base_branch}"],
            cwd=worktree_path,
            check=False,
        )
        if base_result.returncode != 0:
            return False
        base = base_result.stdout.strip()

        # Get merge base
        merge_base_result = run_git(
            ["merge-base", head, base],
            cwd=worktree_path,
            check=False,
        )
        if merge_base_result.returncode != 0:
            return False
        merge_base = merge_base_result.stdout.strip()

        # If merge-base equals head, base is ahead - no conflicts
        if merge_base == head:
            return False

        # Check for file conflicts by doing a dry-run merge
        result = run_git(
            ["merge", "--no-commit", "--no-ff", f"origin/{base_branch}"],
            cwd=worktree_path,
            check=False,
        )
        has_conflict = result.returncode != 0 and "CONFLICT" in result.stdout + result.stderr

        # Abort the merge
        run_git(["merge", "--abort"], cwd=worktree_path, check=False)

        return has_conflict
    except subprocess.CalledProcessError:
        return False


def has_uncommitted_changes(worktree_path: Path) -> bool:
    """Check if worktree has uncommitted changes."""
    try:
        result = run_git(["status", "--porcelain"], cwd=worktree_path, check=False)
        return bool(result.stdout.strip())
    except subprocess.CalledProcessError:
        return False


def get_last_commit_age_days(worktree_path: Path) -> int | None:
    """Get age of last commit in days."""
    try:
        result = run_git(
            ["log", "-1", "--format=%ct"],
            cwd=worktree_path,
            check=False,
        )
        if result.returncode != 0:
            return None
        timestamp = int(result.stdout.strip())
        commit_time = datetime.fromtimestamp(timestamp, tz=UTC)
        age = datetime.now(UTC) - commit_time
        return age.days
    except (subprocess.CalledProcessError, ValueError):
        return None


def is_already_merged(worktree_path: Path, base_branch: str = "main") -> bool:
    """Check if worktree branch is already merged into base."""
    try:
        # Get current branch HEAD
        head_result = run_git(["rev-parse", "HEAD"], cwd=worktree_path, check=False)
        if head_result.returncode != 0:
            return False
        head = head_result.stdout.strip()

        # Check if this commit is an ancestor of origin/base
        result = run_git(
            ["merge-base", "--is-ancestor", head, f"origin/{base_branch}"],
            cwd=worktree_path,
            check=False,
        )
        return result.returncode == 0
    except subprocess.CalledProcessError:
        return False
