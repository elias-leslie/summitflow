"""Path utilities for worktree and workspace management."""

from __future__ import annotations

import os
import re
from pathlib import Path

DEFAULT_WORKSPACES_ROOT = Path("/srv/workspaces")


def get_workspaces_root() -> Path:
    """Return the configured shared workspace root."""
    raw = os.environ.get("ST_WORKSPACES_ROOT")
    if raw:
        return Path(raw).expanduser()
    return DEFAULT_WORKSPACES_ROOT


def get_legacy_worktrees_root() -> Path:
    """Return the legacy per-user worktrees root."""
    return Path.home() / ".local" / "share" / "st" / "worktrees"


def workspaces_root_available() -> bool:
    """Return True when the shared workspace root is available on this host."""
    return get_workspaces_root().is_dir()


def get_projects_base_dir(project_id: str | None = None) -> Path:
    """Return the Btrfs-backed projects base directory when available."""
    base_dir = get_workspaces_root() / "projects"
    if project_id:
        base_dir = base_dir / project_id
    if workspaces_root_available():
        base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir


def get_workspace_snapshots_base_dir(project_id: str | None = None) -> Path:
    """Return the Btrfs-backed snapshots base directory when available."""
    base_dir = get_workspaces_root() / ".snapshots"
    if project_id:
        base_dir = base_dir / project_id
    if workspaces_root_available():
        base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir


def get_lanes_base_dir(project_id: str | None = None) -> Path:
    """Return the Btrfs-backed lanes base directory when available."""
    base_dir = get_workspaces_root() / "lanes"
    if project_id:
        base_dir = base_dir / project_id
    if workspaces_root_available():
        base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir


def get_worktrees_base_dir(project_id: str | None = None) -> Path:
    """Returns worktrees directory for a project.

    Path format:
      - /srv/workspaces/lanes/<project-id>/ when the shared workspace is available
      - ~/.local/share/st/worktrees/<project-id>/ as the legacy fallback
    If project_id is None, returns the base worktrees directory.

    Creates the directory if it doesn't exist.

    Args:
        project_id: Project identifier. If None, returns base worktrees dir.

    Returns:
        Path to the worktrees directory (project-specific if project_id given).
    """
    if workspaces_root_available():
        return get_lanes_base_dir(project_id)

    base_dir = get_legacy_worktrees_root()
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
    sanitized = re.sub(r"[^a-zA-Z0-9_-]", "_", task_id)
    sanitized = re.sub(r"_+", "_", sanitized).strip("_")
    if not sanitized:
        sanitized = "task"
    return sanitized
