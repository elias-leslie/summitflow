"""Worktree creation and initialization."""

from __future__ import annotations

from ....logging_config import get_logger
from ....services.worktree import create_task_worktree
from ....storage import tasks as task_store
from .events import emit_error, emit_log
from .git_ops import has_uncommitted_changes, smart_commit
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
            "Found uncommitted changes from previous session, preserving them on remote",
            project_id=project_id,
        )
        if smart_commit(
            project_path,
            f"wip({task_id}): recover prior worktree changes",
            task_id=task_id,
            push=True,
            skip_checks=True,
        ):
            emit_log(task_id, "info", "Recovered orphaned changes published", project_id=project_id)
        else:
            emit_log(task_id, "warn", "Failed to preserve orphaned worktree changes", project_id=project_id)

    return project_path
