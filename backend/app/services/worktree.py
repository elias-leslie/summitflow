"""Worktree isolation service for autonomous task execution.

Provides worktree operations for Agent Hub task dispatch workflow.
Each dispatched task gets an isolated worktree at:
    ~/.local/share/st/worktrees/<project-id>/<task-id>/

With branch naming:
    <task-id>/main

This module wraps the CLI worktree library for use in Celery tasks.
Creates checkpoint metadata for unified tracking via `st checkpoints`.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from ..logging_config import get_logger
from ..storage.projects import get_project_root_path

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)


def _get_claimed_by() -> str:
    """Get the claimer identity from env or default."""
    return os.getenv("AGENT_ID", "autonomous")


@dataclass
class TaskWorktreeInfo:
    """Information about a task's worktree."""

    path: Path
    branch: str
    task_id: str
    base_branch: str
    is_active: bool = True


class WorktreeError(Exception):
    """Error during worktree operations."""

    pass


def _get_snapshots_dir(project_root: str) -> Path:
    """Get the .st/snapshots directory for a project, creating if needed."""
    snapshots_dir = Path(project_root) / ".st" / "snapshots"
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    return snapshots_dir


def _create_checkpoint_metadata(
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


def _remove_checkpoint_metadata(task_id: str, project_id: str) -> bool:
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
        meta_path = Path(project_root) / ".st" / "snapshots" / f"{task_id}.meta.json"
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


def create_task_worktree(
    task_id: str,
    project_id: str,
    base_branch: str = "main",
) -> TaskWorktreeInfo | None:
    """Create an isolated worktree for a task.

    Creates a worktree at ~/.local/share/st/worktrees/<project-id>/<task-id>/
    with a new branch <task-id>/main based on the specified base branch.

    Args:
        task_id: Task identifier for the worktree
        project_id: Project ID to get the repository root
        base_branch: Branch to base the worktree on (default: main)

    Returns:
        TaskWorktreeInfo with worktree details, or None if creation failed

    Note:
        This function does not raise exceptions - it logs errors and returns None
        to allow execution to fall back to using the project root path.
    """
    try:
        # Import the CLI worktree module
        from cli.lib.worktree import (
            create_worktree,
            get_worktree_info,
        )

        # Check if worktree already exists
        existing = get_worktree_info(task_id, project_id)
        if existing:
            logger.info(
                "worktree_exists",
                task_id=task_id,
                path=str(existing.path),
                branch=existing.branch,
            )
            return TaskWorktreeInfo(
                path=existing.path,
                branch=existing.branch,
                task_id=task_id,
                base_branch=existing.base_branch,
                is_active=existing.is_active,
            )

        # Create new worktree
        worktree_info = create_worktree(task_id, base_branch, project_id)
        logger.info(
            "worktree_created",
            task_id=task_id,
            path=str(worktree_info.path),
            branch=worktree_info.branch,
            base_branch=base_branch,
        )

        # Create checkpoint metadata for unified tracking via `st checkpoints`
        _create_checkpoint_metadata(
            task_id=task_id,
            project_id=project_id,
            base_branch=base_branch,
            worktree_path=str(worktree_info.path),
        )

        return TaskWorktreeInfo(
            path=worktree_info.path,
            branch=worktree_info.branch,
            task_id=task_id,
            base_branch=base_branch,
            is_active=True,
        )

    except ImportError as e:
        logger.warning(
            "worktree_import_error",
            task_id=task_id,
            error=str(e),
            hint="CLI worktree module not available",
        )
        return None
    except Exception as e:
        logger.warning(
            "worktree_creation_failed",
            task_id=task_id,
            project_id=project_id,
            error=str(e),
        )
        return None


def get_task_worktree(task_id: str, project_id: str | None = None) -> TaskWorktreeInfo | None:
    """Get worktree info for a task if it exists.

    Args:
        task_id: Task identifier
        project_id: Project identifier for per-project worktree paths

    Returns:
        TaskWorktreeInfo if worktree exists, None otherwise
    """
    try:
        from cli.lib.worktree import get_worktree_info

        info = get_worktree_info(task_id, project_id)
        if info:
            return TaskWorktreeInfo(
                path=info.path,
                branch=info.branch,
                task_id=task_id,
                base_branch=info.base_branch,
                is_active=info.is_active,
            )
        return None
    except ImportError:
        return None
    except Exception as e:
        logger.debug("worktree_lookup_failed", task_id=task_id, error=str(e))
        return None


def remove_task_worktree(
    task_id: str, delete_branch: bool = False, project_id: str | None = None
) -> bool:
    """Remove a task's worktree and checkpoint metadata.

    Args:
        task_id: Task identifier
        delete_branch: Whether to also delete the associated branch
        project_id: Project identifier for per-project worktree paths

    Returns:
        True if worktree was removed, False otherwise
    """
    try:
        from cli.lib.worktree import remove_worktree

        result = remove_worktree(task_id, delete_branch=delete_branch, project_id=project_id)
        if result:
            logger.info(
                "worktree_removed",
                task_id=task_id,
                branch_deleted=delete_branch,
            )
            # Also remove checkpoint metadata
            if project_id:
                _remove_checkpoint_metadata(task_id, project_id)
        return result
    except ImportError:
        return False
    except Exception as e:
        logger.warning("worktree_removal_failed", task_id=task_id, error=str(e))
        return False


def get_execution_path(task_id: str, project_id: str) -> str:
    """Get the execution path for a task.

    Returns the worktree path if one exists for the task, otherwise falls back
    to the project root path.

    Args:
        task_id: Task identifier
        project_id: Project identifier

    Returns:
        Path to use for task execution (worktree or project root)

    Raises:
        ValueError: If project has no root path configured
    """
    # First, check if a worktree exists for this task
    worktree = get_task_worktree(task_id, project_id)
    if worktree and worktree.is_active:
        logger.debug(
            "using_worktree_path",
            task_id=task_id,
            path=str(worktree.path),
        )
        return str(worktree.path)

    # Fall back to project root path
    project_root = get_project_root_path(project_id)
    if not project_root:
        raise ValueError(f"Project {project_id} has no root_path configured")

    logger.debug(
        "using_project_root_path",
        task_id=task_id,
        project_id=project_id,
        path=project_root,
    )
    return project_root


def ensure_task_worktree(
    task_id: str,
    project_id: str,
    base_branch: str = "main",
) -> str:
    """Ensure a worktree exists for the task and return the execution path.

    Creates a worktree if one doesn't exist. Falls back to project root if
    worktree creation fails.

    Args:
        task_id: Task identifier
        project_id: Project identifier
        base_branch: Branch to base the worktree on

    Returns:
        Path to use for task execution
    """
    # Try to get existing worktree
    worktree = get_task_worktree(task_id, project_id)
    if worktree and worktree.is_active:
        return str(worktree.path)

    # Try to create new worktree
    worktree = create_task_worktree(task_id, project_id, base_branch)
    if worktree:
        return str(worktree.path)

    # Fall back to project root
    project_root = get_project_root_path(project_id)
    if not project_root:
        raise ValueError(f"Project {project_id} has no root_path configured")

    logger.info(
        "worktree_fallback_to_project_root",
        task_id=task_id,
        project_id=project_id,
        path=project_root,
    )
    return project_root


__all__ = [
    "TaskWorktreeInfo",
    "WorktreeError",
    "create_task_worktree",
    "ensure_task_worktree",
    "get_execution_path",
    "get_task_worktree",
    "remove_task_worktree",
]
