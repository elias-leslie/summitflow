"""Task branch checkout setup and initialization."""

from __future__ import annotations

from ....logging_config import get_logger
from ....services.task_checkout import create_task_checkout
from ....storage import tasks as task_store
from .checkout import get_project_path
from .events import emit_error, emit_log
from .git_ops import has_uncommitted_changes, smart_commit_result

logger = get_logger(__name__)


def _preserve_uncommitted_changes(
    task_id: str,
    project_id: str,
    project_path: str,
    *,
    before_checkout: bool,
) -> None:
    if not has_uncommitted_changes(project_path):
        return

    message = (
        "Found uncommitted changes before task branch setup, preserving them on remote"
        if before_checkout
        else "Found uncommitted changes from previous session, preserving them on remote"
    )
    emit_log(task_id, "warn", message, project_id=project_id)
    commit_result = smart_commit_result(
        project_path,
        f"wip({task_id}): recover prior shared-checkout changes",
        task_id=task_id,
        push=True,
        skip_checks=True,
    )
    if commit_result.get("success"):
        emit_log(task_id, "info", "Recovered orphaned changes published", project_id=project_id)
        return

    detail = str(commit_result.get("detail") or "unknown preservation failure")
    emit_log(
        task_id,
        "warn",
        f"Failed to preserve orphaned shared-checkout changes: {detail}",
        project_id=project_id,
    )


def setup_task_checkout(task_id: str, project_id: str) -> str | None:
    """Prepare the shared checkout for task execution.

    Args:
        task_id: The task ID
        project_id: The project ID

    Returns:
        Project path if successful, None if branch preparation failed
    """
    project_path = get_project_path(project_id, task_id)
    _preserve_uncommitted_changes(
        task_id,
        project_id,
        project_path,
        before_checkout=True,
    )

    checkout = create_task_checkout(task_id, project_id)
    if checkout:
        emit_log(task_id, "info", f"Task branch ready in shared checkout: {checkout.branch}", project_id=project_id)
    else:
        emit_error(
            task_id,
            "Task branch setup failed — refusing to execute on main branch",
            recoverable=False,
            project_id=project_id,
        )
        task_store.update_task_status(task_id, "failed")
        return None

    _preserve_uncommitted_changes(
        task_id,
        project_id,
        project_path,
        before_checkout=False,
    )

    return project_path
