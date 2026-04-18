"""Git operations for checkpoint cleanup commands."""

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


def _resolve_base_ref(repo_path: Path, base_branch: str) -> str:
    remote_ref = f"origin/{base_branch}"
    remote_exists = run_git(["rev-parse", "--verify", remote_ref], cwd=repo_path, check=False)
    return remote_ref if remote_exists.returncode == 0 else base_branch


def get_commits_ahead_behind(
    repo_path: Path,
    branch_name: str,
    base_branch: str = "main",
) -> tuple[int, int]:
    """Get number of commits ahead and behind base branch for a task branch."""
    try:
        run_git(["fetch", "origin", base_branch], cwd=repo_path, check=False)
        base_ref = _resolve_base_ref(repo_path, base_branch)

        result = run_git(
            ["rev-list", "--count", f"{base_ref}..{branch_name}"],
            cwd=repo_path,
            check=False,
        )
        ahead = int(result.stdout.strip()) if result.returncode == 0 else 0

        result = run_git(
            ["rev-list", "--count", f"{branch_name}..{base_ref}"],
            cwd=repo_path,
            check=False,
        )
        behind = int(result.stdout.strip()) if result.returncode == 0 else 0

        return ahead, behind
    except (subprocess.CalledProcessError, ValueError, OSError):
        return 0, 0


def has_merge_conflicts(repo_path: Path, branch_name: str, base_branch: str = "main") -> bool:
    """Check if merging base branch into branch_name would cause conflicts."""
    try:
        base_ref = _resolve_base_ref(repo_path, base_branch)
        head_result = run_git(["rev-parse", branch_name], cwd=repo_path, check=False)
        if head_result.returncode != 0:
            return False
        head = head_result.stdout.strip()

        base_result = run_git(
            ["rev-parse", base_ref],
            cwd=repo_path,
            check=False,
        )
        if base_result.returncode != 0:
            return False
        base = base_result.stdout.strip()

        merge_base_result = run_git(
            ["merge-base", head, base],
            cwd=repo_path,
            check=False,
        )
        if merge_base_result.returncode != 0:
            return False
        merge_base = merge_base_result.stdout.strip()

        if merge_base == head:
            return False

        result = run_git(
            ["merge-tree", merge_base, head, base],
            cwd=repo_path,
            check=False,
        )
        return "CONFLICT" in result.stdout + result.stderr
    except (subprocess.CalledProcessError, OSError):
        return False


def has_uncommitted_changes(repo_path: Path, branch_name: str | None = None) -> bool:
    """Check if the current checkout has uncommitted changes for branch_name."""
    try:
        if branch_name:
            current = run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_path, check=False)
            if current.returncode != 0 or current.stdout.strip() != branch_name:
                return False
        result = run_git(["status", "--porcelain"], cwd=repo_path, check=False)
        return bool(result.stdout.strip())
    except (subprocess.CalledProcessError, OSError):
        return False


def get_last_commit_age_days(repo_path: Path, branch_name: str) -> int | None:
    """Get age of last commit on a branch in days."""
    try:
        result = run_git(
            ["log", "-1", "--format=%ct", branch_name],
            cwd=repo_path,
            check=False,
        )
        if result.returncode != 0:
            return None
        timestamp = int(result.stdout.strip())
        commit_time = datetime.fromtimestamp(timestamp, tz=UTC)
        age = datetime.now(UTC) - commit_time
        return age.days
    except (subprocess.CalledProcessError, ValueError, OSError):
        return None


def is_already_merged(repo_path: Path, branch_name: str, base_branch: str = "main") -> bool:
    """Check if branch_name is already merged into base."""
    try:
        head_result = run_git(["rev-parse", branch_name], cwd=repo_path, check=False)
        if head_result.returncode != 0:
            return False
        head = head_result.stdout.strip()
        base_ref = _resolve_base_ref(repo_path, base_branch)

        result = run_git(
            ["merge-base", "--is-ancestor", head, base_ref],
            cwd=repo_path,
            check=False,
        )
        return result.returncode == 0
    except (subprocess.CalledProcessError, OSError):
        return False
