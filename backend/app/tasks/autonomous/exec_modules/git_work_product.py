"""Git work-product helpers for autonomous execution."""

from __future__ import annotations

from .events import emit_log
from .git_ops import (
    has_uncommitted_changes,
    has_unpublished_commits,
    publish_existing_commits,
    smart_commit_result,
)


def ensure_committed_work_product(
    task_id: str,
    subtask_short_id: str,
    project_path: str,
    project_id: str,
) -> str | None:
    """Ensure verified autonomous work is committed and pushed to main.

    Returns:
        None on success, or an error string when the work product could not be
        preserved on the remote.
    """
    if has_unpublished_commits(project_path):
        return None if publish_existing_commits(project_path) else "Failed to publish existing commits"

    if not has_uncommitted_changes(project_path):
        return "No committed or dirty work product remains to publish"

    commit_message = f"autocode({task_id}): complete subtask {subtask_short_id}"
    commit_result = smart_commit_result(
        project_path,
        commit_message,
        task_id=task_id,
        push=True,
    )
    if not commit_result.get("success"):
        return str(commit_result.get("detail") or "Failed to preserve verified work on remote")

    emit_log(
        task_id,
        "info",
        f"Published verified work product for subtask {subtask_short_id}",
        source="orchestrator",
        project_id=project_id,
    )

    if not has_unpublished_commits(project_path):
        return None
    return "Commit completed but work is still unpublished"
