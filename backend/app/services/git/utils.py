"""Git utility operations."""

from __future__ import annotations

import subprocess
from pathlib import Path

from ...logging_config import get_logger
from ...utils import safe_subprocess

logger = get_logger(__name__)


def push_branch(
    branch_name: str,
    project_path: str | Path,
    set_upstream: bool = True,
) -> bool:
    """Push a branch to remote origin.

    Args:
        branch_name: Name of the branch to push
        project_path: Path to the git repository
        set_upstream: Whether to set upstream tracking (default True)

    Returns:
        True if successful

    Raises:
        RuntimeError: If push fails
    """
    project_path = Path(project_path)

    cmd = ["git", "push"]
    if set_upstream:
        cmd.extend(["-u", "origin", branch_name])
    else:
        cmd.extend(["origin", branch_name])

    result = safe_subprocess.run(
        ["git", "-C", str(project_path), *cmd[1:]],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        logger.error("push_failed", branch=branch_name, error=result.stderr)
        raise RuntimeError(f"Failed to push branch: {result.stderr}")

    logger.info("branch_pushed", branch=branch_name)
    return True


def revert_to(repo_path: Path | str, sha: str) -> bool:
    """Hard reset repository to a specific commit.

    WARNING: This is destructive! All uncommitted changes will be lost.

    Args:
        repo_path: Path to the git repository
        sha: Commit SHA to reset to

    Returns:
        True if successful

    Raises:
        RuntimeError: If reset fails
    """
    repo_path = Path(repo_path)

    result = safe_subprocess.run(
        ["git", "-C", str(repo_path), "reset", "--hard", sha],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        logger.error("revert_failed", sha=sha[:8], error=result.stderr)
        raise RuntimeError(f"Failed to revert to {sha}: {result.stderr}")

    logger.info("reverted", sha=sha[:8])
    return True


def get_head_sha(repo_path: str | Path) -> str:
    """Get the current HEAD commit SHA.

    Args:
        repo_path: Path to git repository

    Returns:
        Full commit SHA
    """
    repo_path = Path(repo_path)

    result = safe_subprocess.run(
        ["git", "-C", str(repo_path), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(f"Failed to get HEAD SHA: {result.stderr}")

    return result.stdout.strip()


def get_blob_shas(repo_path: str | Path, paths: list[str]) -> dict[str, str]:
    """Get blob SHAs for specific files (for rebase-resistant tracking).

    Args:
        repo_path: Path to git repository
        paths: List of file paths to get SHAs for

    Returns:
        Dict mapping file paths to their blob SHAs
    """
    repo_path = Path(repo_path)
    result: dict[str, str] = {}

    for path in paths:
        try:
            proc = safe_subprocess.run(
                ["git", "-C", str(repo_path), "ls-files", "-s", path],
                capture_output=True,
                text=True,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                # Output format: <mode> <sha> <stage>\t<file>
                parts = proc.stdout.split()
                if len(parts) >= 2:
                    result[path] = parts[1]
        except subprocess.SubprocessError:
            pass  # Skip files that don't exist or error

    return result
