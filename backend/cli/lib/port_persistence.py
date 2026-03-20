"""Port persistence utilities for worktree service isolation.

Provides functions to save and load port assignments from disk.
"""

from __future__ import annotations

import json
from pathlib import Path


def _resolve_project_id(task_id: str, project_id: str | None) -> str | None:
    if project_id:
        return project_id

    from .checkpoint_metadata import load_snapshot_meta

    meta = load_snapshot_meta(task_id)
    return meta.project_id if meta else None


def get_ports_file(task_id: str, project_id: str | None = None) -> Path:
    """Get path to ports.json for a worktree.

    Args:
        task_id: The task identifier.
        project_id: Optional project identifier.

    Returns:
        Path to the ports.json file.
    """
    from .worktree import get_worktree_path

    return get_worktree_path(task_id, _resolve_project_id(task_id, project_id)) / "ports.json"


def load_ports_dict(task_id: str, project_id: str | None = None) -> dict[str, str | int] | None:
    """Load port assignments from disk.

    Args:
        task_id: The task identifier.
        project_id: Optional project identifier.

    Returns:
        Dictionary with port data if found, None otherwise.
    """
    ports_file = get_ports_file(task_id, project_id)
    if not ports_file.exists():
        return None

    try:
        data: dict[str, str | int] = json.loads(ports_file.read_text())
        return data
    except (json.JSONDecodeError, KeyError, TypeError):
        return None


def save_ports_dict(
    task_id: str,
    ports_data: dict[str, str | int],
    project_id: str | None = None,
) -> None:
    """Save port assignments to disk.

    Args:
        task_id: The task identifier.
        ports_data: Dictionary with port data to save.
        project_id: Optional project identifier.
    """
    from .worktree import get_worktree_path

    worktree_path = get_worktree_path(task_id, _resolve_project_id(task_id, project_id))
    if not worktree_path.exists():
        return

    ports_file = worktree_path / "ports.json"
    ports_file.write_text(json.dumps(ports_data, indent=2))


def delete_ports_file(task_id: str, project_id: str | None = None) -> bool:
    """Delete port assignments file.

    Args:
        task_id: The task identifier.
        project_id: Optional project identifier.

    Returns:
        True if file was deleted, False if it didn't exist.
    """
    ports_file = get_ports_file(task_id, project_id)
    if ports_file.exists():
        ports_file.unlink()
        return True
    return False
