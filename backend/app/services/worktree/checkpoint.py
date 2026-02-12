"""Checkpoint metadata management for worktrees.

Creates and manages .st/snapshots/<task_id>.meta.json files for
unified tracking via `st checkpoints`.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from ...logging_config import get_logger
from ...storage.projects import get_project_root_path

logger = get_logger(__name__)


def _get_claimed_by() -> str:
    """Get the claimer identity from env or default."""
    return os.getenv("AGENT_ID", "autonomous")


def _get_snapshots_dir(project_root: str) -> Path:
    """Get the .st/snapshots directory for a project, creating if needed."""
    snapshots_dir = Path(project_root) / ".st" / "snapshots"
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    return snapshots_dir


def create_checkpoint_metadata(
    task_id: str,
    project_id: str,
    base_branch: str,
    worktree_path: str,
) -> bool:
    """Create checkpoint metadata file for unified tracking.

    Creates .st/snapshots/<task_id>.meta.json in the project root.
    This enables `st checkpoints` to show autonomous task worktrees.

    Args:
        task_id: Task identifier
        project_id: Project identifier
        base_branch: Branch the worktree is based on
        worktree_path: Path to the worktree

    Returns:
        True if metadata was created, False on error
    """
    project_root = get_project_root_path(project_id)
    if not project_root:
        logger.warning(
            "checkpoint_metadata_skipped",
            task_id=task_id,
            reason="no project root path",
        )
        return False

    try:
        snapshots_dir = _get_snapshots_dir(project_root)
        meta_path = snapshots_dir / f"{task_id}.meta.json"

        if meta_path.exists():
            logger.debug("checkpoint_metadata_exists", task_id=task_id)
            return True

        metadata = {
            "task_id": task_id,
            "project_id": project_id,
            "base_branch": base_branch,
            "created_at": datetime.now(UTC).isoformat(),
            "claimed_by": _get_claimed_by(),
            "worktree_path": worktree_path,
            "backend_port": None,
            "frontend_port": None,
        }

        meta_path.write_text(json.dumps(metadata, indent=2))
        logger.info(
            "checkpoint_metadata_created",
            task_id=task_id,
            path=str(meta_path),
        )
        return True

    except Exception as e:
        logger.warning(
            "checkpoint_metadata_failed",
            task_id=task_id,
            error=str(e),
        )
        return False


def remove_checkpoint_metadata(task_id: str, project_id: str) -> bool:
    """Remove checkpoint metadata file.

    Args:
        task_id: Task identifier
        project_id: Project identifier

    Returns:
        True if metadata was removed or didn't exist, False on error
    """
    project_root = get_project_root_path(project_id)
    if not project_root:
        return True

    try:
        from cli.lib.checkpoint_metadata import get_meta_path

        meta_path = get_meta_path(task_id, project_root)
        if meta_path.exists():
            meta_path.unlink()
            logger.info("checkpoint_metadata_removed", task_id=task_id)
        return True
    except Exception as e:
        logger.warning(
            "checkpoint_metadata_removal_failed",
            task_id=task_id,
            error=str(e),
        )
        return False


__all__ = [
    "create_checkpoint_metadata",
    "remove_checkpoint_metadata",
]
