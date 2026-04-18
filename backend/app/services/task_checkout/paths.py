"""Execution path resolution for task-branch execution."""

from __future__ import annotations

from ...logging_config import get_logger
from ...storage.projects import get_project_root_path
from .operations import create_task_checkout, get_task_checkout

logger = get_logger(__name__)


def get_execution_path(task_id: str, project_id: str) -> str:
    """Get the execution path for a task.

    Returns the project root path for the task.

    Args:
        task_id: Task identifier
        project_id: Project identifier

    Returns:
        Path to use for task execution

    Raises:
        ValueError: If project has no root path configured
    """
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


def ensure_task_checkout(
    task_id: str,
    project_id: str,
    base_branch: str = "main",
) -> str:
    """Ensure the task branch exists and return the project root path.

    Args:
        task_id: Task identifier
        project_id: Project identifier
        base_branch: Branch to base the task branch on

    Returns:
        Path to use for task execution
    """
    checkout = get_task_checkout(task_id, project_id)
    if checkout and checkout.is_active:
        return str(checkout.path)

    checkout = create_task_checkout(task_id, project_id, base_branch)
    if checkout:
        return str(checkout.path)

    project_root = get_project_root_path(project_id)
    if not project_root:
        raise ValueError(f"Project {project_id} has no root_path configured")

    logger.info(
        "task_branch_fallback_to_project_root",
        task_id=task_id,
        project_id=project_id,
        path=project_root,
    )
    return project_root


__all__ = [
    "ensure_task_checkout",
    "get_execution_path",
]
