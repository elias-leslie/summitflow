"""Git worktree operations."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from ...logging_config import get_logger
from .utils import get_head_sha

logger = get_logger(__name__)


def auto_claim_with_worktree(
    task_id: str,
    project_path: str | Path,
    project_id: str,
) -> dict[str, Any]:
    """Claim a task and create an isolated worktree for agent execution.

    This is the entry point for agent workflows. It:
    1. Creates a worktree for the task
    2. Updates the task with worktree info
    3. Returns the worktree path for agent execution

    Args:
        task_id: Task ID to claim
        project_path: Path to main git repository
        project_id: Project ID for task lookups

    Returns:
        Dict with worktree_path, branch_name, and base_sha

    Raises:
        RuntimeError: If worktree creation fails
    """
    from ..worktree_manager import WorktreeManager

    project_path = Path(project_path)
    manager = WorktreeManager(project_path)

    try:
        # Capture the base SHA before creating worktree (for rebase-resistant review)
        base_sha = get_head_sha(project_path)

        # Create worktree
        worktree_info = manager.create_worktree(project_id, task_id)

        # Update task with branch info (worktree path derivable from task_id)
        from ...storage import tasks as task_store

        task_store.update_task(
            task_id,
            branch_name=worktree_info.branch,
            status="running",
        )

        logger.info(
            "agent_claim_complete",
            task_id=task_id,
            worktree=str(worktree_info.path),
            branch=worktree_info.branch,
        )

        return {
            "worktree_path": str(worktree_info.path),
            "branch_name": worktree_info.branch,
            "base_sha": base_sha,
        }

    except Exception as e:
        logger.error("agent_claim_failed", task_id=task_id, error=str(e))
        raise RuntimeError(f"Failed to claim task with worktree: {e}") from e


def get_worktree_changes(worktree_path: str | Path) -> dict[str, Any]:
    """Get summary of changes in a worktree.

    Args:
        worktree_path: Path to the worktree

    Returns:
        Dict with files_changed, additions, deletions, affected_files
    """
    worktree_path = Path(worktree_path)

    # Get diff stats against the base branch
    result = subprocess.run(
        ["git", "diff", "--stat", "HEAD~1..HEAD"],
        cwd=worktree_path,
        capture_output=True,
        text=True,
    )

    # Parse the last line for summary (e.g., "3 files changed, 10 insertions(+), 5 deletions(-)")
    affected_files: list[str] = []
    stats: dict[str, Any] = {
        "files_changed": 0,
        "additions": 0,
        "deletions": 0,
        "affected_files": affected_files,
    }

    if result.returncode == 0:
        lines = result.stdout.strip().split("\n")

        # Get affected files (all lines except the last summary line)
        for line in lines[:-1]:
            parts = line.split("|")
            if len(parts) >= 1:
                file_path = parts[0].strip()
                if file_path:
                    stats["affected_files"].append(file_path)

        # Parse summary line
        if lines:
            summary = lines[-1]

            files_match = re.search(r"(\d+) files? changed", summary)
            ins_match = re.search(r"(\d+) insertions?", summary)
            del_match = re.search(r"(\d+) deletions?", summary)

            if files_match:
                stats["files_changed"] = int(files_match.group(1))
            if ins_match:
                stats["additions"] = int(ins_match.group(1))
            if del_match:
                stats["deletions"] = int(del_match.group(1))

    return stats
