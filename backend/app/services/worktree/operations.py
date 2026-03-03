"""Worktree CRUD operations.

Provides worktree creation, retrieval, and removal operations.
Wraps the CLI worktree library for use in background tasks.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from ...logging_config import get_logger
from .checkpoint import create_checkpoint_metadata, remove_checkpoint_metadata
from .types import TaskWorktreeInfo

logger = get_logger(__name__)


class WorktreeInfoLike(Protocol):
    """Protocol for worktree info objects from CLI library."""

    path: Path
    branch: str
    base_branch: str
    is_active: bool


def _to_task_worktree_info(
    info: WorktreeInfoLike,
    task_id: str,
    base_branch: str | None = None,
    is_active: bool | None = None,
) -> TaskWorktreeInfo:
    """Build a TaskWorktreeInfo from a cli worktree info object."""
    return TaskWorktreeInfo(
        path=info.path,
        branch=info.branch,
        task_id=task_id,
        base_branch=base_branch if base_branch is not None else info.base_branch,
        is_active=is_active if is_active is not None else info.is_active,
    )


def create_task_worktree(
    task_id: str,
    project_id: str,
    base_branch: str = "main",
) -> TaskWorktreeInfo | None:
    """Create an isolated worktree for a task."""
    try:
        from cli.lib.worktree import create_worktree, get_worktree_info

        existing = get_worktree_info(task_id, project_id)
        if existing:
            logger.info(
                "worktree_exists",
                task_id=task_id,
                path=str(existing.path),
                branch=existing.branch,
            )
            return _to_task_worktree_info(existing, task_id)
        worktree_info = create_worktree(task_id, base_branch, project_id)
        logger.info(
            "worktree_created",
            task_id=task_id,
            path=str(worktree_info.path),
            branch=worktree_info.branch,
            base_branch=base_branch,
        )
        create_checkpoint_metadata(
            task_id=task_id,
            project_id=project_id,
            base_branch=base_branch,
            worktree_path=str(worktree_info.path),
        )
        return _to_task_worktree_info(worktree_info, task_id, base_branch, True)

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


def get_task_worktree(
    task_id: str, project_id: str | None = None
) -> TaskWorktreeInfo | None:
    """Return TaskWorktreeInfo for *task_id* if a worktree exists, else None."""
    try:
        from cli.lib.worktree import get_worktree_info

        info = get_worktree_info(task_id, project_id)
        if info:
            return _to_task_worktree_info(info, task_id)
        return None
    except ImportError:
        return None
    except Exception as e:
        logger.debug("worktree_lookup_failed", task_id=task_id, error=str(e))
        return None


def remove_task_worktree(
    task_id: str, delete_branch: bool = False, project_id: str | None = None
) -> bool:
    """Remove a task's worktree and checkpoint metadata; return True on success."""
    try:
        from cli.lib.worktree import remove_worktree

        result = remove_worktree(
            task_id, delete_branch=delete_branch, project_id=project_id
        )
        if result:
            logger.info(
                "worktree_removed",
                task_id=task_id,
                branch_deleted=delete_branch,
            )
            # Also remove checkpoint metadata
            if project_id:
                remove_checkpoint_metadata(task_id, project_id)
        return result
    except ImportError:
        return False
    except Exception as e:
        logger.warning("worktree_removal_failed", task_id=task_id, error=str(e))
        return False


__all__ = [
    "create_task_worktree",
    "get_task_worktree",
    "remove_task_worktree",
]
