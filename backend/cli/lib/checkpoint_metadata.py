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

    def to_dict(self) -> dict[str, str]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SnapshotMeta:
        """Create from dictionary."""
        d = data.copy()
        # Ignore legacy lane-era fields when loading old metadata.
        d.pop("snapshot_path", None)
        d.pop("backend_port", None)
        d.pop("frontend_port", None)

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


def _legacy_snapshots_dir(project_root: str | Path | None = None) -> Path:
    """Return the legacy checkout-local snapshots directory."""
    base = Path(project_root) if project_root else Path.cwd()
    snapshots_dir = base / ".st" / "snapshots"
    snapshots_dir.mkdir(parents=True, exist_ok=True)

    gitignore = base / ".st" / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("snapshots/\n")
    elif "snapshots/" not in gitignore.read_text():
        with gitignore.open("a") as f:
            f.write("snapshots/\n")

    return snapshots_dir


def get_snapshots_dir(
    project_id: str | None = None,
    project_root: str | Path | None = None,
) -> Path:
    """Get the checkpoint metadata directory.

    New storage is global and project-scoped. Legacy checkout-local paths are
    still available for backwards-compatible reads.
    """
    if project_id:
        target = _global_checkpoints_base() / project_id
        target.mkdir(parents=True, exist_ok=True)
        return target
    return _legacy_snapshots_dir(project_root)


def get_meta_path(
    task_id: str,
    project_root: str | Path | None = None,
    project_id: str | None = None,
) -> Path:
    """Get path for task snapshot metadata file."""
    task_id = canonicalize_task_id(task_id)
    return get_snapshots_dir(project_id=project_id, project_root=project_root) / f"{task_id}.meta.json"


def _find_global_meta_path(task_id: str, project_id: str | None = None) -> Path | None:
    """Search global checkpoint storage for a task metadata file."""
    task_id = canonicalize_task_id(task_id)
    if project_id:
        candidate = get_meta_path(task_id, project_id=project_id)
        return candidate if candidate.exists() else None

    for meta_path in _global_checkpoints_base().glob(f"*/{task_id}.meta.json"):
        return meta_path
    return None


def load_snapshot_meta(task_id: str, project_root: str | Path | None = None) -> SnapshotMeta | None:
    """Load snapshot metadata for a task.

    Args:
        task_id: Task identifier
        project_root: Optional project root path

    Returns:
        SnapshotMeta if found, None otherwise
    """
    task_id = canonicalize_task_id(task_id)
    meta_path = _find_global_meta_path(task_id)
    if meta_path is None:
        meta_path = get_meta_path(task_id, project_root=project_root)
    if not meta_path.exists() and project_root is not None:
        meta_path = get_meta_path(task_id)
    if not meta_path.exists():
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
