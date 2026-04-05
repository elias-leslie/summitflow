"""Worktree analysis logic for cleanup commands."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.storage import tasks as task_store

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


_CLEANUP_ELIGIBLE_TASK_STATUSES = {
    "completed",
    "completed_ready_for_closure",
    "reconciled",
    "done",
}

_CLEANUP_ELIGIBLE_LIFECYCLES = {
    "authoritative,superseded",
    "reconciled",
    "retired",
    "retired_lane_no_action",
}


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


def get_task_info(task_id: str) -> tuple[str | None, str | None]:
    """Get task status and title. Returns (status, title) or (None, None) if not found."""
    task = task_store.get_task(task_id)
    if not task:
        return None, None
    status = task.get("status")
    lifecycle = task.get("lifecycle")
    if lifecycle in _CLEANUP_ELIGIBLE_LIFECYCLES and status not in _CLEANUP_ELIGIBLE_TASK_STATUSES:
        status = "reconciled"
    return status, task.get("title")


def _determine_action(
    task_status: str | None,
    commits_ahead: int,
    is_merged: bool,
    has_uncommitted: bool,
    has_conflicts: bool,
) -> tuple[CleanupAction, str]:
    """Determine cleanup action and reason from git/task state."""
    if task_status in ("running", "pending"):
        return CleanupAction.TASK_ACTIVE, f"Task is {task_status}"
    if has_uncommitted:
        return CleanupAction.MANUAL_REVIEW, "Has uncommitted changes"
    if task_status == "cancelled":
        if is_merged or commits_ahead == 0:
            reason = "Cancelled task can be discarded"
        elif has_conflicts:
            reason = "Cancelled task branch conflicts with main and can be discarded"
        else:
            reason = f"Cancelled task has {commits_ahead} unmerged commit(s) and can be discarded"
        return CleanupAction.SAFE_DELETE, reason
    if task_status == "failed":
        if is_merged or commits_ahead == 0:
            action = CleanupAction.ALREADY_MERGED if is_merged else CleanupAction.SAFE_DELETE
            reason = "Already merged" if is_merged else f"{task_status.capitalize()} task has no commits ahead of main"
        else:
            action = CleanupAction.MANUAL_REVIEW
            reason = f"{task_status.capitalize()} task has unmerged commits and requires review before cleanup"
        return action, reason
    if task_status in _CLEANUP_ELIGIBLE_TASK_STATUSES:
        if is_merged or commits_ahead == 0:
            action = CleanupAction.ALREADY_MERGED if is_merged else CleanupAction.SAFE_DELETE
            reason = "Already merged" if is_merged else f"{task_status.capitalize()} residue can be discarded"
            return action, reason
        return CleanupAction.MANUAL_REVIEW, f"{task_status.capitalize()} residue still has unmerged commits"
    if has_conflicts:
        return CleanupAction.HAS_CONFLICTS, "Would conflict with main"
    if is_merged or commits_ahead == 0:
        action = CleanupAction.ALREADY_MERGED if is_merged else CleanupAction.SAFE_DELETE
        return action, "Already merged" if is_merged else "No commits ahead of main"
    if commits_ahead > 0:
        return CleanupAction.NEEDS_MERGE, f"{commits_ahead} commit(s) not in main"
    return CleanupAction.MANUAL_REVIEW, "Complex state"


def analyze_worktree(worktree: WorktreeInfo) -> WorktreeAnalysis:
    """Analyze a worktree and recommend cleanup action."""
    task_status, task_title = get_task_info(worktree.task_id)

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

    commits_ahead, commits_behind = get_commits_ahead_behind(worktree.path, worktree.base_branch)
    has_uncommitted = has_uncommitted_changes(worktree.path)
    has_conflicts = has_merge_conflicts(worktree.path, worktree.base_branch)
    last_commit_age = get_last_commit_age_days(worktree.path)
    is_merged = is_already_merged(worktree.path, worktree.base_branch)

    action, reason = _determine_action(task_status, commits_ahead, is_merged, has_uncommitted, has_conflicts)

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


def categorize_analysis(analysis: WorktreeAnalysis) -> tuple[str, str]:
    """Return category label and display reason for a worktree analysis."""
    if analysis.action in (CleanupAction.SAFE_DELETE, CleanupAction.ALREADY_MERGED):
        return "SAFE", analysis.reason
    if analysis.action == CleanupAction.NEEDS_MERGE:
        return "NEEDS_MERGE", analysis.reason
    if analysis.action == CleanupAction.HAS_CONFLICTS:
        return "CONFLICT", analysis.reason
    if analysis.action == CleanupAction.TASK_ACTIVE:
        return "ACTIVE", analysis.reason
    return "REVIEW", analysis.reason


def format_analysis(analysis: WorktreeAnalysis) -> str:
    """Render a compact cleanup analysis line."""
    category, reason = categorize_analysis(analysis)
    return f"{analysis.worktree.task_id} [{category}] {reason}"


def cleanup_worktree(analysis: WorktreeAnalysis, force: bool = False) -> tuple[bool, str]:
    """Cleanup a worktree based on analysis.

    Returns:
        (success, message)
    """
    if analysis.action == CleanupAction.TASK_ACTIVE and not force:
        return False, "Cannot remove active task worktree without --force"

    if analysis.action in (CleanupAction.NEEDS_MERGE, CleanupAction.HAS_CONFLICTS, CleanupAction.MANUAL_REVIEW) and not force:
        return False, f"Worktree requires manual review: {analysis.reason}"

    try:
        success = remove_worktree(
            analysis.worktree.task_id,
            delete_branch=True,
            project_id=analysis.worktree.project_id,
        )
    except Exception as exc:
        return False, f"Error: {exc}"
    if success:
        return True, f"Removed {analysis.worktree.task_id}"
    return False, f"Failed to remove {analysis.worktree.task_id}"
