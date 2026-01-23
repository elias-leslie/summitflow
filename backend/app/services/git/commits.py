"""Git commit operations."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from ...logging_config import get_logger

logger = get_logger(__name__)


def commit_changes(
    message: str,
    project_path: str | Path,
    add_all: bool = True,
) -> str | None:
    """Create a git commit with staged changes.

    Args:
        message: Commit message
        project_path: Path to the git repository
        add_all: Whether to add all changes before committing

    Returns:
        Commit SHA if successful, None if nothing to commit
    """
    project_path = Path(project_path)

    if add_all:
        # Stage all changes
        result = subprocess.run(
            ["git", "add", "-A"],
            cwd=project_path,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            logger.error("git_add_failed", error=result.stderr)
            raise RuntimeError(f"Failed to stage changes: {result.stderr}")

    # Check if there are changes to commit
    check_result: subprocess.CompletedProcess[bytes] = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=project_path,
        capture_output=True,
    )

    if check_result.returncode == 0:
        # No changes staged
        logger.info("no_changes_to_commit")
        return None

    # Create commit
    result = subprocess.run(
        ["git", "commit", "-m", message],
        cwd=project_path,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        logger.error("commit_failed", error=result.stderr)
        raise RuntimeError(f"Failed to commit: {result.stderr}")

    # Get commit SHA
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=project_path,
        capture_output=True,
        text=True,
    )

    commit_sha = result.stdout.strip()
    logger.info("commit_created", sha=commit_sha[:8])
    return commit_sha


def get_current_commit(repo_path: Path | str) -> str:
    """Get the current HEAD commit SHA.

    Args:
        repo_path: Path to the git repository

    Returns:
        Full commit SHA
    """
    repo_path = Path(repo_path)

    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(f"Failed to get current commit: {result.stderr}")

    return result.stdout.strip()


def capture_diff(
    repo_path: Path | str,
    base_sha: str,
    head_sha: str = "HEAD",
) -> str:
    """Capture git diff between two commits.

    Args:
        repo_path: Path to the git repository
        base_sha: Base commit SHA
        head_sha: Head commit SHA (default: HEAD)

    Returns:
        Unified diff output as string
    """
    repo_path = Path(repo_path)

    result = subprocess.run(
        ["git", "diff", f"{base_sha}..{head_sha}", "--unified=3"],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(f"Failed to capture diff: {result.stderr}")

    return result.stdout


def get_diff_stats(
    repo_path: Path | str,
    base_sha: str,
    head_sha: str = "HEAD",
) -> dict[str, Any]:
    """Get statistics from a git diff.

    Args:
        repo_path: Path to the git repository
        base_sha: Base commit SHA
        head_sha: Head commit SHA (default: HEAD)

    Returns:
        Dict with files_changed, insertions, deletions
    """
    repo_path = Path(repo_path)

    result = subprocess.run(
        ["git", "diff", f"{base_sha}..{head_sha}", "--shortstat"],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(f"Failed to get diff stats: {result.stderr}")

    stats = {
        "files_changed": 0,
        "insertions": 0,
        "deletions": 0,
    }

    # Parse output like: " 3 files changed, 10 insertions(+), 5 deletions(-)"
    output = result.stdout.strip()
    if output:
        # Extract numbers using regex
        files_match = re.search(r"(\d+) files? changed", output)
        insertions_match = re.search(r"(\d+) insertions?\(\+\)", output)
        deletions_match = re.search(r"(\d+) deletions?\(-\)", output)

        if files_match:
            stats["files_changed"] = int(files_match.group(1))
        if insertions_match:
            stats["insertions"] = int(insertions_match.group(1))
        if deletions_match:
            stats["deletions"] = int(deletions_match.group(1))

    return stats
