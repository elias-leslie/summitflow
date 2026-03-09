"""Git work-product helpers for autonomous execution."""

from __future__ import annotations

import subprocess

from .events import emit_log

_COMMIT_TIMEOUT_SECONDS = 30


def _git(project_path: str, *args: str) -> subprocess.CompletedProcess[str]:
    """Run a git command inside the task worktree."""
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


def _has_dirty_changes(project_path: str) -> bool:
    """Return True when the task worktree has uncommitted changes."""
    result = _git(project_path, "status", "--porcelain")
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
        committed into the task branch.
    """
    if _has_branch_commits(project_path):
        return None

    if not _has_dirty_changes(project_path):
        return "No committed or dirty work product remains to merge"

    add_result = _git(project_path, "add", "-A")
    if add_result.returncode != 0:
        return (add_result.stderr or add_result.stdout or "git add failed").strip()

    commit_message = f"autocode({task_id}): complete subtask {subtask_short_id}"
    commit_result = _git(project_path, "commit", "-m", commit_message)
    if commit_result.returncode != 0:
        return (commit_result.stderr or commit_result.stdout or "git commit failed").strip()

    emit_log(
        task_id,
        "info",
        f"Committed verified work product for subtask {subtask_short_id}",
        source="orchestrator",
        project_id=project_id,
    )

    if _has_branch_commits(project_path):
        return None
    return "Commit completed but branch still has no commits beyond main"
