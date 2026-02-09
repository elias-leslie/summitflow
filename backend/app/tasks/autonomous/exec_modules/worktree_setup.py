"""Worktree creation and initialization."""

from __future__ import annotations

from ....logging_config import get_logger
from ....services.worktree import create_task_worktree
from ....storage import tasks as task_store
from .events import emit_error, emit_log
from .git_ops import auto_commit, has_uncommitted_changes
from .worktree import get_project_path

logger = get_logger(__name__)


def setup_worktree(task_id: str, project_id: str) -> str | None:
    """Create worktree and handle orphaned changes.

    Args:
        task_id: The task ID
        project_id: The project ID

    Returns:
        Project path if successful, None if worktree creation failed
    """
    worktree = create_task_worktree(task_id, project_id)
    if worktree:
        emit_log(task_id, "info", f"Worktree ready: {worktree.path}", project_id=project_id)
    else:
        emit_error(
            task_id,
            "Worktree creation failed — refusing to execute on main branch",
            recoverable=False,
            project_id=project_id,
        )
        task_store.update_task_status(task_id, "blocked")
        return None

    project_path = get_project_path(project_id, task_id)
    if has_uncommitted_changes(project_path):
        emit_log(
            task_id,
            "warn",
            "Found uncommitted changes from previous session, auto-committing",
            project_id=project_id,
        )
        if auto_commit(project_path, "WIP: uncommitted changes from previous session"):
            emit_log(task_id, "info", "Orphaned changes committed", project_id=project_id)

    return project_path
