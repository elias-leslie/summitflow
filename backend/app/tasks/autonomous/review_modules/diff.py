"""Git diff extraction for review."""

from __future__ import annotations

import subprocess

from ....services.worktree import get_execution_path
from ..verification_helpers import get_diff_range


def get_git_diff(task_id: str, project_id: str) -> str:
    """Get git diff for the task, using worktree if available.

    Args:
        task_id: Task ID to check for worktree
        project_id: Project ID for fallback path

    Returns:
        Git diff output or error message
    """
    try:
        cwd = get_execution_path(task_id, project_id)
        result = subprocess.run(
            ["git", "diff", get_diff_range(cwd)],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=cwd,
        )
        return result.stdout or "(no changes)"
    except Exception as e:
        return f"(error getting diff: {e})"
