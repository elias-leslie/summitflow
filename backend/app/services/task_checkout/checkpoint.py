"""Checkpoint metadata management for task branches.

Writes task checkpoint metadata to the global checkpoint store
(``~/.local/share/st/checkpoints/<project_id>/``) so `st checkpoints`,
`st cleanup`, and the block-main-edits hook share a single source of truth.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

from ...logging_config import get_logger
from ...storage.projects import get_project_root_path
from ...utils import safe_subprocess
from ...utils.git_base import normalize_base_branch

logger = get_logger(__name__)


def _get_claimed_by() -> str:
    """Get the claimer identity from env or default."""
    return os.getenv("AGENT_ID", "autonomous")


def _get_main_repo_dirty_paths(project_root: str) -> list[str]:
    """Capture the current dirty file paths in the main repo.

    This becomes the baseline for detecting later writes that leaked out of a
    task checkout into the shared project root.
    """
    try:
        result = safe_subprocess.run(
            ["git", "-C", str(project_root), "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except Exception as e:
        logger.warning("checkpoint_dirty_baseline_failed", project_root=project_root, error=str(e))
        return []

    paths: list[str] = []
    for raw_line in result.stdout.splitlines():
        line = raw_line.rstrip()
        if len(line) < 4:
            continue
        path_field = line[3:]
        if " -> " in path_field:
            path_field = path_field.split(" -> ", 1)[1]
        if path_field:
            paths.append(path_field)
    return paths


def create_checkpoint_metadata(
    task_id: str,
    project_id: str,
    base_branch: str,
) -> bool:
    """Create checkpoint metadata in the global checkpoint store."""
    project_root = get_project_root_path(project_id)
    if not project_root:
        logger.warning(
            "checkpoint_metadata_skipped",
            task_id=task_id,
            reason="no project root path",
        )
        return False

    try:
        from cli.lib.checkpoint_metadata import (
            SnapshotMeta,
            get_meta_path,
            save_snapshot_meta,
        )

        if get_meta_path(task_id, project_id=project_id).exists():
            logger.debug("checkpoint_metadata_exists", task_id=task_id)
            return True

        meta = SnapshotMeta(
            task_id=task_id,
            project_id=project_id,
            base_branch=normalize_base_branch(base_branch, project_root),
            created_at=datetime.now(UTC).isoformat(),
            claimed_by=_get_claimed_by(),
            main_repo_dirty_paths=_get_main_repo_dirty_paths(project_root),
        )
        save_snapshot_meta(meta)
        logger.info(
            "checkpoint_metadata_created",
            task_id=task_id,
            path=str(get_meta_path(task_id, project_id=project_id)),
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
    """Remove checkpoint metadata from the global checkpoint store."""
    try:
        from cli.lib.checkpoint_metadata import get_meta_path

        meta_path = get_meta_path(task_id, project_id=project_id)
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
