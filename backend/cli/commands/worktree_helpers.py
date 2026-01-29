"""Helper functions for worktree management."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.worktree_manager import WorktreeManager

from .worktree_git_ops import get_project_root

# Base directory for all worktrees (project-agnostic)
# Note: WorktreeManager uses /tmp/summitflow-worktrees by default
WORKTREE_BASE = Path("/tmp/st-worktrees")


def get_worktree_manager() -> WorktreeManager:
    """Get WorktreeManager instance for current project."""
    from app.services.worktree_manager import WorktreeManager

    project_root = get_project_root()
    return WorktreeManager(project_root)


def cleanup_empty_directories(
    project_id: str,
    all_projects: bool = False,
) -> list[str]:
    """Clean up empty directories in worktree base.

    Args:
        project_id: Current project ID
        all_projects: Whether to clean all projects or just current one

    Returns:
        List of removed directory paths
    """
    removed_dirs: list[str] = []
    if not WORKTREE_BASE.exists():
        return removed_dirs

    if all_projects:
        # Clean all project directories
        dirs_to_check = list(WORKTREE_BASE.iterdir())
    else:
        # Only clean current project's directory
        project_dir = WORKTREE_BASE / project_id
        dirs_to_check = [project_dir] if project_dir.exists() else []

    for project_dir in dirs_to_check:
        if project_dir.is_dir():
            for task_dir in project_dir.iterdir():
                if task_dir.is_dir() and not any(task_dir.iterdir()):
                    task_dir.rmdir()
                    removed_dirs.append(str(task_dir))
            if not any(project_dir.iterdir()):
                project_dir.rmdir()
                removed_dirs.append(str(project_dir))

    return removed_dirs
