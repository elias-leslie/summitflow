"""Branch query operations for checkpoints command.

Provides utilities for querying task branches, unmerged commits, and orphaned branches.
"""

from __future__ import annotations

import subprocess

from ..lib.checkpoint import get_snapshot_info


def get_task_branches(task_id: str) -> list[dict[str, str]]:
    """Get all branches for a task (task branch + subtask branches)."""
    branches = []
    try:
        result = subprocess.run(
            ["git", "branch", "--list", f"{task_id}/*"],
            capture_output=True,
            text=True,
            check=True,
        )
        for line in result.stdout.splitlines():
            branch = line.strip().lstrip("* ")
            if branch:
                # Determine if it's a subtask or task branch
                # Task branch ends with /main, subtask branches end with /X.Y
                suffix = branch.split("/")[-1] if "/" in branch else ""
                if suffix == "main":
                    branches.append({"branch": branch, "subtask_id": "", "type": "task"})
                else:
                    branches.append({"branch": branch, "subtask_id": suffix, "type": "subtask"})
    except subprocess.CalledProcessError:
        pass
    return branches


def get_branch_unmerged_commits(branch: str) -> list[dict[str, str]]:
    """Get unmerged commits for a branch (commits not in main)."""
    commits = []
    try:
        result = subprocess.run(
            ["git", "log", f"main..{branch}", "--oneline", "--format=%H|%s|%ar"],
            capture_output=True,
            text=True,
            check=True,
        )
        for line in result.stdout.strip().splitlines():
            if "|" in line:
                parts = line.split("|", 2)
                if len(parts) == 3:
                    commits.append(
                        {
                            "hash": parts[0][:8],
                            "message": parts[1],
                            "age": parts[2],
                        }
                    )
    except subprocess.CalledProcessError:
        pass
    return commits


def get_orphaned_branches() -> list[str]:
    """Find task branches without corresponding metadata."""
    orphaned = []
    try:
        result = subprocess.run(
            ["git", "branch", "--list", "task-*/*"],
            capture_output=True,
            text=True,
            check=True,
        )
        for line in result.stdout.splitlines():
            branch = line.strip().lstrip("*+ ")
            if not branch:
                continue
            # Extract task_id from branch name (e.g., "task-abc123/main" -> "task-abc123")
            task_id = branch.split("/")[0] if "/" in branch else branch
            # Check if metadata exists for this task
            info = get_snapshot_info(task_id)
            if not info:
                orphaned.append(branch)
    except subprocess.CalledProcessError:
        pass
    return orphaned
