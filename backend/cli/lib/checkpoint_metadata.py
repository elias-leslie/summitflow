"""Checkpoint metadata and helper utilities.

Provides SnapshotMeta dataclass and helper functions for checkpoint management.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from app.storage.tasks import canonicalize_task_id
from app.utils.git_base import current_branch_or_base, normalize_base_branch


@dataclass
class SnapshotMeta:
    """Metadata for a task checkpoint."""

    task_id: str
    project_id: str
    base_branch: str
    created_at: str  # ISO format
    claimed_by: str

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SnapshotMeta:
        """Create from dictionary."""
        d = data.copy()
        # Ignore legacy fields when loading old metadata.
        d.pop("snapshot_path", None)
        d.pop("backend_port", None)
        d.pop("frontend_port", None)
        d.pop("main_repo_dirty_paths", None)

        # Cast to required types to satisfy LSP
        return cls(
            task_id=str(d["task_id"]),
            project_id=str(d["project_id"]),
            base_branch=normalize_base_branch(str(d["base_branch"])),
            created_at=str(d["created_at"]),
            claimed_by=str(d["claimed_by"]),
        )


def _global_checkpoints_base() -> Path:
    """Return the global checkpoint metadata base directory."""
    base = Path.home() / ".local" / "share" / "st" / "checkpoints"
    base.mkdir(parents=True, exist_ok=True)
    return base


def get_snapshots_dir(project_id: str) -> Path:
    """Get the project-scoped checkpoint metadata directory."""
    target = _global_checkpoints_base() / project_id
    target.mkdir(parents=True, exist_ok=True)
    return target


def get_meta_path(task_id: str, project_id: str) -> Path:
    """Get path for task snapshot metadata file."""
    return get_snapshots_dir(project_id) / f"{canonicalize_task_id(task_id)}.meta.json"


def _find_global_meta_path(task_id: str) -> Path | None:
    """Search global checkpoint storage for a task metadata file."""
    task_id = canonicalize_task_id(task_id)
    for meta_path in _global_checkpoints_base().glob(f"*/{task_id}.meta.json"):
        return meta_path
    return None


def load_snapshot_meta(task_id: str) -> SnapshotMeta | None:
    """Load snapshot metadata for a task from the global checkpoint store."""
    meta_path = _find_global_meta_path(canonicalize_task_id(task_id))
    if meta_path is None or not meta_path.exists():
        return None

    try:
        return SnapshotMeta.from_dict(json.loads(meta_path.read_text()))
    except (json.JSONDecodeError, KeyError):
        return None


def save_snapshot_meta(meta: SnapshotMeta) -> None:
    """Save snapshot metadata to disk.

    Args:
        meta: SnapshotMeta to save
    """
    meta_path = get_meta_path(meta.task_id, project_id=meta.project_id)
    meta_path.write_text(json.dumps(meta.to_dict(), indent=2))


def get_claimed_by() -> str:
    """Get the claimer identity from env or git config."""
    # Try AGENT_ID first (for agent workflows)
    agent_id = os.getenv("AGENT_ID")
    if agent_id:
        return agent_id

    # Fall back to git user
    try:
        result = subprocess.run(
            ["git", "config", "user.name"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip() or "unknown"
    except subprocess.CalledProcessError:
        return "unknown"


def get_current_branch() -> str:
    """Get current git branch name."""
    return current_branch_or_base()


def is_working_tree_clean() -> bool:
    """Check if git working tree is clean."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=True,
        )
        return len(result.stdout.strip()) == 0
    except subprocess.CalledProcessError:
        return False
