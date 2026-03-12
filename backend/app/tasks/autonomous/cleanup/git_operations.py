"""Low-level git operations for merge and cleanup tasks."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass

from ....logging_config import get_logger

logger = get_logger(__name__)


def _format_merge_error(result: subprocess.CompletedProcess[str], task_branch: str) -> str:
    """Build a useful merge error message even when git leaves stderr empty."""
    detail = ((result.stderr or "").strip() or (result.stdout or "").strip())
    if not detail:
        detail = f"git merge exited with code {result.returncode}"
    return f"Failed to merge {task_branch}: {detail}"


@dataclass
class MergeOutcome:
    """Result of a merge attempt with structured conflict info."""

    success: bool
    merge_sha: str | None = None
    error: str | None = None
    conflicting_files: list[str] | None = None


def checkout_base_branch(project_root: str, base_branch: str) -> str | None:
    """Checkout base branch in main repo.

    Args:
        project_root: Path to project root directory
        base_branch: Name of base branch to checkout

    Returns:
        Error message if checkout failed, None if successful
    """
    result = subprocess.run(
        ["git", "checkout", base_branch],
        cwd=project_root,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        return f"Failed to checkout {base_branch}: {result.stderr}"
    return None


def merge_task_branch(
    project_root: str,
    task_branch: str,
    task_id: str,
) -> MergeOutcome:
    """Merge task branch into current branch.

    Args:
        project_root: Path to project root directory
        task_branch: Name of task branch to merge
        task_id: Task ID for commit message

    Returns:
        MergeOutcome with success/failure details and merge SHA.
    """
    branch_check = subprocess.run(
        ["git", "show-ref", "--verify", f"refs/heads/{task_branch}"],
        cwd=project_root,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if branch_check.returncode != 0:
        return MergeOutcome(
            success=False,
            error=f"Failed to merge {task_branch}: branch not found",
        )

    result = subprocess.run(
        ["git", "merge", "--no-ff", task_branch, "-m", f"Merge task {task_id}"],
        cwd=project_root,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        merge_output = "\n".join(
            part.strip() for part in (result.stderr or "", result.stdout or "") if part.strip()
        )
        conflicting = extract_conflicting_files(merge_output)
        subprocess.run(
            ["git", "merge", "--abort"],
            cwd=project_root,
            capture_output=True,
            timeout=10,
        )
        return MergeOutcome(
            success=False,
            error=_format_merge_error(result, task_branch),
            conflicting_files=conflicting if conflicting else None,
        )

    # Capture the merge commit SHA
    sha_result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=project_root,
        capture_output=True,
        text=True,
        timeout=10,
    )
    merge_sha = sha_result.stdout.strip() if sha_result.returncode == 0 else None

    return MergeOutcome(success=True, merge_sha=merge_sha)


def extract_conflicting_files(stderr: str) -> list[str]:
    """Extract conflicting file paths from git merge stderr output.

    Parses lines like:
        CONFLICT (content): Merge conflict in src/api/foo.py

    Args:
        stderr: The stderr output from a failed git merge

    Returns:
        List of conflicting file paths.
    """
    files: list[str] = []
    for match in re.finditer(r"CONFLICT.*?:\s+.*?in\s+(.+?)$", stderr, re.MULTILINE):
        files.append(match.group(1).strip())
    return files


def delete_task_branch(
    project_root: str,
    task_branch: str,
    task_id: str,
) -> bool:
    """Delete task branch after merge.

    Args:
        project_root: Path to project root directory
        task_branch: Name of branch to delete
        task_id: Task ID for logging

    Returns:
        True if branch was deleted, False otherwise
    """
    result = subprocess.run(
        ["git", "branch", "-d", task_branch],
        cwd=project_root,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        logger.warning(
            "Failed to delete branch %s: %s",
            task_branch, result.stderr,
            extra={"task_id": task_id},
        )
        return False
    return True


def revert_merge_commit(task_id: str, project_root: str) -> bool:
    """Revert the most recent merge commit.

    Args:
        task_id: Task ID for logging
        project_root: Path to project root directory

    Returns:
        True if revert succeeded, False otherwise
    """
    from app.storage import log_task_event

    result = subprocess.run(
        ["git", "revert", "--no-edit", "-m", "1", "HEAD"],
        cwd=project_root,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        log_task_event(
            task_id,
            f"Auto-rollback FAILED: could not revert merge: {result.stderr[:200]}",
        )
        logger.error(
            "Auto-rollback failed",
            extra={"task_id": task_id, "error": result.stderr[:200]},
        )
        return False
    return True
