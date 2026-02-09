"""Worktree health checking and project path utilities."""

from __future__ import annotations

import subprocess
from pathlib import Path

from ....logging_config import get_logger
from ....services.worktree import get_execution_path
from ....storage.projects import get_project_root_path
from .events import emit_log

logger = get_logger(__name__)


def get_project_path(project_id: str, task_id: str | None = None) -> str:
    """Get execution path for task, using worktree if available.

    Args:
        project_id: Project ID for fallback to root path
        task_id: Task ID to check for worktree (optional)

    Returns:
        Worktree path if task has one, otherwise project root path

    Raises:
        ValueError: If project has no root_path configured
    """
    if task_id:
        # Use worktree-aware function that checks for task worktree first
        return get_execution_path(task_id, project_id)

    # Fallback for cases without task_id (e.g., pristine checks)
    project_root = get_project_root_path(project_id)
    if not project_root:
        raise ValueError(f"Project {project_id} has no root_path configured")
    return project_root


def check_worktree_health(project_path: str, task_id: str, project_id: str) -> bool:
    """Check worktree is still a valid git working directory."""
    path = Path(project_path)
    if not path.is_dir():
        emit_log(
            task_id, "error",
            f"WORKTREE GONE: {project_path} removed during execution",
            source="orchestrator", project_id=project_id,
        )
        return False
    if not (path / ".git").exists():
        emit_log(
            task_id, "error",
            f"WORKTREE CORRUPTED: {project_path} not a git worktree",
            source="orchestrator", project_id=project_id,
        )
        return False
    return True


def check_main_repo_leakage(
    task_id: str, project_id: str, project_path: str,
) -> bool:
    """Detect if agent wrote files to main repo instead of worktree.

    Compares project_path (worktree) against project root. If they differ
    and main repo has new uncommitted changes, the agent leaked files.

    Returns True if leakage detected, False otherwise.
    """
    main_root = get_project_root_path(project_id)
    if not main_root or main_root == project_path:
        return False

    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=main_root,
            capture_output=True,
            text=True,
            timeout=30,
        )
        dirty_files = result.stdout.strip()
        if dirty_files:
            emit_log(
                task_id,
                "warn",
                f"WORKTREE LEAKAGE: Agent modified main repo. "
                f"Files: {dirty_files[:200]}",
                source="orchestrator",
                project_id=project_id,
            )
            return True
    except Exception as e:
        logger.warning("main_repo_leakage_check_failed", error=str(e))

    return False
