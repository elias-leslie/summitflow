"""Checkpoint metadata and helper utilities.

Provides SnapshotMeta dataclass and helper functions for checkpoint management.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class SnapshotMeta:
    """Metadata for a task checkpoint (worktree isolation)."""

    task_id: str
    project_id: str
    base_branch: str
    created_at: str  # ISO format
    claimed_by: str
    worktree_path: str | None = None  # Path to isolated worktree
    backend_port: int | None = None  # Allocated backend port for worktree
    frontend_port: int | None = None  # Allocated frontend port for worktree

    def to_dict(self) -> dict[str, str | int | None]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, str | int | None]) -> SnapshotMeta:
        """Create from dictionary."""
        # Handle older snapshots without worktree_path
        if "worktree_path" not in data:
            data["worktree_path"] = None
        # Handle older snapshots without port info
        if "backend_port" not in data:
            data["backend_port"] = None
        if "frontend_port" not in data:
            data["frontend_port"] = None
        # Handle older snapshots with snapshot_path (no longer used)
        data.pop("snapshot_path", None)
        return cls(**data)


def get_snapshots_dir() -> Path:
    """Get the .st/snapshots directory, creating if needed."""
    snapshots_dir = Path.cwd() / ".st" / "snapshots"
    snapshots_dir.mkdir(parents=True, exist_ok=True)

    # Ensure .st/.gitignore ignores snapshots
    gitignore = Path.cwd() / ".st" / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("snapshots/\n")
    elif "snapshots/" not in gitignore.read_text():
        with gitignore.open("a") as f:
            f.write("snapshots/\n")

    return snapshots_dir


def get_meta_path(task_id: str) -> Path:
    """Get path for task snapshot metadata file."""
    return get_snapshots_dir() / f"{task_id}.meta.json"


def load_snapshot_meta(task_id: str) -> SnapshotMeta | None:
    """Load snapshot metadata for a task.

    Args:
        task_id: Task identifier

    Returns:
        SnapshotMeta if found, None otherwise
    """
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
    meta_path = get_meta_path(meta.task_id)
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
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return "main"


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
