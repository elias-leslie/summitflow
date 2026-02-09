"""Path utilities for worktree management."""

from __future__ import annotations

import re
from pathlib import Path


def get_worktrees_base_dir(project_id: str | None = None) -> Path:
    """Returns worktrees directory for a project.

    Path format: ~/.local/share/st/worktrees/<project-id>/
    If project_id is None, returns the base worktrees directory.

    Creates the directory if it doesn't exist.

    Args:
        project_id: Project identifier. If None, returns base worktrees dir.

    Returns:
        Path to the worktrees directory (project-specific if project_id given).
    """
    base_dir = Path.home() / ".local" / "share" / "st" / "worktrees"
    if project_id:
        base_dir = base_dir / project_id
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir


def get_worktree_path(task_id: str, project_id: str | None = None) -> Path:
    """Returns the path for a specific task's worktree.

    Args:
        task_id: The task identifier.
        project_id: Project identifier for per-project paths.

    Returns:
        Path to the worktree directory.
    """
    sanitized = sanitize_task_id(task_id)
    return get_worktrees_base_dir(project_id) / sanitized


def sanitize_task_id(task_id: str) -> str:
    """Sanitize task ID for safe use in file paths.

    Args:
        task_id: The raw task identifier.

    Returns:
        Sanitized task ID safe for paths.
    """
    # Replace any characters that aren't alphanumeric, dash, or underscore
    sanitized = re.sub(r"[^a-zA-Z0-9_-]", "_", task_id)
    # Remove leading/trailing underscores and collapse multiple underscores
    sanitized = re.sub(r"_+", "_", sanitized).strip("_")
    # Ensure we have something
    if not sanitized:
        sanitized = "task"
    return sanitized
