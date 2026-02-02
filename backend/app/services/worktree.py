"""Worktree isolation service for autonomous task execution.

Provides worktree operations for Agent Hub task dispatch workflow.
Each dispatched task gets an isolated worktree at:
    ~/.summitflow/worktrees/<task-id>/

With branch naming:
    <task-id>/main

This module wraps the CLI worktree library for use in Celery tasks.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from ..logging_config import get_logger
from ..storage.projects import get_project_root_path

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)


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


def create_task_worktree(
    task_id: str,
    project_id: str,
    base_branch: str = "main",
) -> TaskWorktreeInfo | None:
    """Create an isolated worktree for a task.

    Creates a worktree at ~/.summitflow/worktrees/<task-id>/ with a new branch
    <task-id>/main based on the specified base branch.

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
        existing = get_worktree_info(task_id)
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
        worktree_info = create_worktree(task_id, base_branch)
        logger.info(
            "worktree_created",
            task_id=task_id,
            path=str(worktree_info.path),
            branch=worktree_info.branch,
            base_branch=base_branch,
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


def get_task_worktree(task_id: str) -> TaskWorktreeInfo | None:
    """Get worktree info for a task if it exists.

    Args:
        task_id: Task identifier

    Returns:
        TaskWorktreeInfo if worktree exists, None otherwise
    """
    try:
        from cli.lib.worktree import get_worktree_info

        info = get_worktree_info(task_id)
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


def remove_task_worktree(task_id: str, delete_branch: bool = False) -> bool:
    """Remove a task's worktree.

    Args:
        task_id: Task identifier
        delete_branch: Whether to also delete the associated branch

    Returns:
        True if worktree was removed, False otherwise
    """
    try:
        from cli.lib.worktree import remove_worktree

        result = remove_worktree(task_id, delete_branch=delete_branch)
        if result:
            logger.info(
                "worktree_removed",
                task_id=task_id,
                branch_deleted=delete_branch,
            )
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
    worktree = get_task_worktree(task_id)
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
    worktree = get_task_worktree(task_id)
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
