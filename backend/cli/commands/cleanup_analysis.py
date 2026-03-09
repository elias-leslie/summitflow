"""Worktree analysis logic for cleanup commands."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ..client import APIError, STClient
from ..lib.worktree import WorktreeInfo, remove_worktree
from .cleanup_git import (
    get_commits_ahead_behind,
    get_last_commit_age_days,
    has_merge_conflicts,
    has_uncommitted_changes,
    is_already_merged,
)


class CleanupAction(StrEnum):
    """Recommended action for a stale worktree."""

    SAFE_DELETE = "safe_delete"  # No commits ahead, safe to remove
    ALREADY_MERGED = "already_merged"  # Commits already in main
    NEEDS_MERGE = "needs_merge"  # Has commits not in main
    HAS_CONFLICTS = "has_conflicts"  # Would conflict with main
    MANUAL_REVIEW = "manual_review"  # Complex state, needs human review
    TASK_ACTIVE = "task_active"  # Task still running/pending


@dataclass
class WorktreeAnalysis:
    """Analysis result for a worktree."""

    worktree: WorktreeInfo
    task_status: str | None  # None if task not found
    task_title: str | None
    commits_ahead: int
    commits_behind: int
    has_conflicts: bool
    has_uncommitted: bool
    last_commit_age_days: int | None
    action: CleanupAction
    reason: str


def get_task_info(client: STClient, task_id: str) -> tuple[str | None, str | None]:
    """Get task status and title. Returns (status, title) or (None, None) if not found."""
    try:
        task = client.get_task(task_id)
        return task.get("status"), task.get("title")
    except APIError:
        return None, None


def analyze_worktree(worktree: WorktreeInfo, client: STClient) -> WorktreeAnalysis:
    """Analyze a worktree and recommend cleanup action."""
    task_status, task_title = get_task_info(client, worktree.task_id)

    if not worktree.path.exists() or not (worktree.path / ".git").exists():
        return WorktreeAnalysis(
            worktree=worktree,
            task_status=task_status,
            task_title=task_title,
            commits_ahead=0,
            commits_behind=0,
            has_conflicts=False,
            has_uncommitted=False,
            last_commit_age_days=None,
            action=CleanupAction.SAFE_DELETE,
            reason="Worktree path already removed; prune stale registration",
        )

    # Get git state
    commits_ahead, commits_behind = get_commits_ahead_behind(worktree.path, worktree.base_branch)
    has_uncommitted = has_uncommitted_changes(worktree.path)
    has_conflicts = has_merge_conflicts(worktree.path, worktree.base_branch)
    last_commit_age = get_last_commit_age_days(worktree.path)
    is_merged = is_already_merged(worktree.path, worktree.base_branch)

    # Determine action
    if task_status in ("running", "pending", "queue"):
        action = CleanupAction.TASK_ACTIVE
        reason = f"Task is {task_status}"
    elif has_uncommitted:
        action = CleanupAction.MANUAL_REVIEW
        reason = "Has uncommitted changes"
    elif task_status == "cancelled":
        action = CleanupAction.SAFE_DELETE
        if is_merged or commits_ahead == 0:
            reason = "Cancelled task can be discarded"
        elif has_conflicts:
            reason = "Cancelled task branch conflicts with main and can be discarded"
        else:
            reason = f"Cancelled task has {commits_ahead} unmerged commit(s) and can be discarded"
    elif has_conflicts:
        action = CleanupAction.HAS_CONFLICTS
        reason = "Would conflict with main"
    elif is_merged or commits_ahead == 0:
        action = CleanupAction.SAFE_DELETE if not is_merged else CleanupAction.ALREADY_MERGED
        reason = "Already merged" if is_merged else "No commits ahead of main"
    elif commits_ahead > 0:
        action = CleanupAction.NEEDS_MERGE
        reason = f"{commits_ahead} commit(s) not in main"
    else:
        action = CleanupAction.MANUAL_REVIEW
        reason = "Complex state"

    return WorktreeAnalysis(
        worktree=worktree,
        task_status=task_status,
        task_title=task_title,
        commits_ahead=commits_ahead,
        commits_behind=commits_behind,
        has_conflicts=has_conflicts,
        has_uncommitted=has_uncommitted,
        last_commit_age_days=last_commit_age,
        action=action,
        reason=reason,
    )


_ACTION_ICONS = {
    CleanupAction.SAFE_DELETE: "[SAFE]",
    CleanupAction.ALREADY_MERGED: "[MERGED]",
    CleanupAction.NEEDS_MERGE: "[NEEDS_MERGE]",
    CleanupAction.HAS_CONFLICTS: "[CONFLICT]",
    CleanupAction.MANUAL_REVIEW: "[REVIEW]",
    CleanupAction.TASK_ACTIVE: "[ACTIVE]",
}


def format_analysis(analysis: WorktreeAnalysis) -> str:
    """Format analysis for display."""
    icon = _ACTION_ICONS.get(analysis.action, "[?]")
    task_info = f"task:{analysis.task_status or 'NOT_FOUND'}"
    title = analysis.task_title[:40] if analysis.task_title else "?"
    age = analysis.last_commit_age_days
    age_str = f"{age}d" if age is not None else "?"
    commits_str = f"+{analysis.commits_ahead}/-{analysis.commits_behind}"
    flags = (["dirty"] if analysis.has_uncommitted else []) + (
        ["conflicts"] if analysis.has_conflicts else []
    )
    flags_str = ",".join(flags) if flags else "-"
    tid = analysis.worktree.task_id
    return (
        f"{icon} {tid}|{task_info}|{commits_str}|age:{age_str}|"
        f"{flags_str}|{analysis.reason}|{title}"
    )


def cleanup_worktree(analysis: WorktreeAnalysis, force: bool = False) -> tuple[bool, str]:
    """Cleanup a worktree based on analysis. Returns (success, message)."""
    action = analysis.action
    if not analysis.worktree.path.exists():
        return True, "Already removed"
    if not force and action == CleanupAction.TASK_ACTIVE:
        return False, f"Skipped: task is {analysis.task_status}"
    if not force and action == CleanupAction.NEEDS_MERGE:
        return False, f"Skipped: has {analysis.commits_ahead} unmerged commit(s)"
    if not force and action == CleanupAction.HAS_CONFLICTS:
        return False, "Skipped: would conflict with main"
    if not force and action == CleanupAction.MANUAL_REVIEW:
        return False, f"Skipped: {analysis.reason}"
    try:
        success = remove_worktree(
            analysis.worktree.task_id,
            delete_branch=True,
            project_id=analysis.worktree.project_id,
        )
    except Exception as e:
        return False, f"Error: {e}"

    return (True, "Removed") if success else (False, "Worktree not found")
