"""Path utilities for shared workspace management."""

from __future__ import annotations

import os
import re
from pathlib import Path

DEFAULT_WORKSPACES_ROOT = Path.home() / ".local" / "share" / "summitflow" / "workspaces"


def get_workspaces_root() -> Path:
    """Return the configured shared workspace root."""
    raw = os.environ.get("ST_WORKSPACES_ROOT")
    if raw:
        return Path(raw).expanduser()
    return DEFAULT_WORKSPACES_ROOT


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


def get_cache_base_dir(cache_name: str | None = None) -> Path:
    """Return the shared Btrfs-backed cache base directory when available."""
    base_dir = get_workspaces_root() / "cache"
    if cache_name:
        base_dir = base_dir / cache_name
    if workspaces_root_available():
        base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir


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
