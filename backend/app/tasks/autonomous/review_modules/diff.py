"""Git diff extraction for review."""

from __future__ import annotations

import subprocess

from ....storage.projects import get_project_root_path
from ..verification_helpers import get_diff_range


def get_git_diff(task_id: str, project_id: str) -> str:
    """Get git diff for the task against the project root.

    Args:
        task_id: Task ID (unused; retained for call-site compatibility)
        project_id: Project ID for resolving the working directory

    Returns:
        Git diff output or error message
    """
    del task_id
    try:
        cwd = get_project_root_path(project_id)
        if not cwd:
            return "(error getting diff: no project root configured)"
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
