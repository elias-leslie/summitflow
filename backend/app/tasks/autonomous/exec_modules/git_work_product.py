"""Git work-product helpers for autonomous execution."""

from __future__ import annotations

import subprocess

from .events import emit_log
from .git_ops import (
    has_uncommitted_changes,
    has_unpublished_commits,
    publish_existing_commits,
    smart_commit_result,
)

_COMMIT_TIMEOUT_SECONDS = 30


def _git(project_path: str, *args: str) -> subprocess.CompletedProcess[str]:
    """Run a git command inside the shared task checkout."""
    return subprocess.run(
        ["git", *args],
        cwd=project_path,
        capture_output=True,
        text=True,
        timeout=_COMMIT_TIMEOUT_SECONDS,
    )


def _has_branch_commits(project_path: str) -> bool:
    """Return True when the task branch is ahead of main."""
    result = _git(project_path, "log", "--oneline", "main..HEAD")
    return bool(result.stdout and result.stdout.strip())


def ensure_committed_work_product(
    task_id: str,
    subtask_short_id: str,
    project_path: str,
    project_id: str,
) -> str | None:
    """Ensure verified autonomous work exists as a branch commit.

    Returns:
        None on success, or an error string when the work product could not be
        preserved on the task branch remote.
    """
    if _has_branch_commits(project_path):
        return None if publish_existing_commits(project_path) else "Failed to publish existing branch commits"

    if not has_uncommitted_changes(project_path):
        return "No committed or dirty work product remains to merge"

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

    if _has_branch_commits(project_path) and not has_unpublished_commits(project_path):
        return None
    return "Commit completed but branch work is still unpublished"
