"""Git work-product helpers for autonomous execution."""

from __future__ import annotations

from .events import emit_log
from .git_ops import (
    _run_git,
    has_uncommitted_changes,
    smart_commit_result,
)


def ensure_committed_work_product(
    task_id: str,
    subtask_short_id: str,
    project_path: str,
    project_id: str,
) -> str | None:
    """Preserve verified autonomous work locally; publication is independent.

    Returns:
        None on success, or an error string when the work product could not be
        preserved in local history.
    """
    if not has_uncommitted_changes(project_path):
        from app.storage.tasks import get_task

        head = _run_git(project_path, "rev-parse", "HEAD")
        task = get_task(task_id) or {}
        if head.returncode == 0 and head.stdout.strip() in (task.get("commits") or []):
            return None
        return "No task-linked local commit or dirty work product remains"

    commit_message = f"autocode({task_id}): complete subtask {subtask_short_id}"
    commit_result = smart_commit_result(
        project_path,
        commit_message,
        task_id=task_id,
        push=False,
    )
    if not commit_result.get("success"):
        return str(commit_result.get("detail") or "Failed to preserve verified work locally")

    emit_log(
        task_id,
        "info",
        f"Committed verified work product locally for subtask {subtask_short_id}",
        source="orchestrator",
        project_id=project_id,
    )

    return None
