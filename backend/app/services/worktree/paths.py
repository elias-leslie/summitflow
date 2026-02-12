"""Execution path resolution for tasks.

Determines whether to use worktree or project root for task execution.
"""

from __future__ import annotations

from ...logging_config import get_logger
from ...storage.projects import get_project_root_path
from .operations import create_task_worktree, get_task_worktree

logger = get_logger(__name__)


def get_execution_path(task_id: str, project_id: str) -> str:
    """Get the execution path for a task.

    Returns the worktree path if one exists for the task, otherwise falls
    back to the project root path.

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
    "ensure_task_worktree",
    "get_execution_path",
]
