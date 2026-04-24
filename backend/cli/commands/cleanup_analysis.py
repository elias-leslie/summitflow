"""Checkpoint analysis logic for cleanup commands."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from app.storage import tasks as task_store
from app.storage.projects import get_project_root_path

from ..lib.checkpoint import SnapshotMeta, remove_snapshot
from ..lib.checkpoint_branches import get_task_branches, resolve_task_branch
from .cleanup_git import (
    get_commits_ahead_behind,
    get_last_commit_age_days,
    has_merge_conflicts,
    has_uncommitted_changes,
    is_already_merged,
    run_git,
)


class CleanupAction(StrEnum):
    """Recommended action for checkpoint cleanup."""

    SAFE_DELETE = "safe_delete"
    ALREADY_MERGED = "already_merged"
    NEEDS_MERGE = "needs_merge"
    HAS_CONFLICTS = "has_conflicts"
    MANUAL_REVIEW = "manual_review"
    TASK_ACTIVE = "task_active"


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


@dataclass(frozen=True)
class CheckpointResidue:
    """One checkpoint branch plus its repo context."""

    task_id: str
    project_id: str
    repo_path: Path | None
    branch: str
    base_branch: str


@dataclass
class CheckpointAnalysis:
    """Analysis result for one checkpoint residue item."""

    checkpoint: CheckpointResidue
    task_status: str | None
    task_title: str | None
    commits_ahead: int
    commits_behind: int
    has_conflicts: bool
    has_uncommitted: bool
    last_commit_age_days: int | None
    action: CleanupAction
    reason: str


def get_task_info(task_id: str) -> tuple[str | None, str | None]:
    """Get task status and title. Returns (None, None) if not found."""
    task = task_store.get_task(task_id)
    if not task:
        return None, None
    status = task.get("status")
    lifecycle = task.get("lifecycle")
    if lifecycle in _CLEANUP_ELIGIBLE_LIFECYCLES and status not in _CLEANUP_ELIGIBLE_TASK_STATUSES:
        status = "reconciled"
    return status, task.get("title")


def _repo_path(project_id: str) -> Path | None:
    root = get_project_root_path(project_id)
    return Path(root).resolve() if root else None


def _branch_name(checkpoint: SnapshotMeta) -> str:
    return resolve_task_branch(checkpoint.task_id, project_id=checkpoint.project_id)


def _branch_exists(repo_path: Path, branch: str) -> bool:
    return run_git(["rev-parse", "--verify", branch], cwd=repo_path, check=False).returncode == 0


def _build_checkpoint_residue(checkpoint: SnapshotMeta) -> CheckpointResidue:
    return CheckpointResidue(
        task_id=checkpoint.task_id,
        project_id=checkpoint.project_id,
        repo_path=_repo_path(checkpoint.project_id),
        branch=_branch_name(checkpoint),
        base_branch=checkpoint.base_branch or "main",
    )


def _determine_action(
    task_status: str | None,
    commits_ahead: int,
    is_merged: bool,
    has_uncommitted: bool,
    has_conflicts: bool,
) -> tuple[CleanupAction, str]:
    if task_status in {"running", "pending"}:
        return CleanupAction.TASK_ACTIVE, f"Task is {task_status}"
    if has_uncommitted:
        return CleanupAction.MANUAL_REVIEW, "Current checkout has uncommitted changes"
    if task_status == "cancelled":
        if is_merged or commits_ahead == 0:
            return CleanupAction.SAFE_DELETE, "Cancelled task can be discarded"
        if has_conflicts:
            return CleanupAction.SAFE_DELETE, "Cancelled task conflicts with base and can be discarded"
        return CleanupAction.SAFE_DELETE, f"Cancelled task has {commits_ahead} unmerged commit(s) and can be discarded"
    if task_status == "failed":
        if is_merged or commits_ahead == 0:
            action = CleanupAction.ALREADY_MERGED if is_merged else CleanupAction.SAFE_DELETE
            reason = "Already merged" if is_merged else "Failed task has no commits ahead of base"
            return action, reason
        return CleanupAction.MANUAL_REVIEW, "Failed task still has unmerged commits"
    if task_status in _CLEANUP_ELIGIBLE_TASK_STATUSES:
        if is_merged or commits_ahead == 0:
            action = CleanupAction.ALREADY_MERGED if is_merged else CleanupAction.SAFE_DELETE
            reason = "Already merged" if is_merged else f"{task_status.capitalize()} residue can be discarded"
            return action, reason
        return CleanupAction.MANUAL_REVIEW, f"{task_status.capitalize()} residue still has unmerged commits"
    if has_conflicts:
        return CleanupAction.HAS_CONFLICTS, "Would conflict with base"
    if is_merged or commits_ahead == 0:
        action = CleanupAction.ALREADY_MERGED if is_merged else CleanupAction.SAFE_DELETE
        return action, "Already merged" if is_merged else "No commits ahead of base"
    if commits_ahead > 0:
        return CleanupAction.NEEDS_MERGE, f"{commits_ahead} commit(s) not in base"
    return CleanupAction.MANUAL_REVIEW, "Complex state"


def analyze_checkpoint(checkpoint: SnapshotMeta) -> CheckpointAnalysis:
    """Analyze a checkpoint and recommend cleanup action."""
    residue = _build_checkpoint_residue(checkpoint)
    task_status, task_title = get_task_info(checkpoint.task_id)

    if residue.repo_path is None or not residue.repo_path.exists():
        return CheckpointAnalysis(
            checkpoint=residue,
            task_status=task_status,
            task_title=task_title,
            commits_ahead=0,
            commits_behind=0,
            has_conflicts=False,
            has_uncommitted=False,
            last_commit_age_days=None,
            action=CleanupAction.SAFE_DELETE,
            reason="Checkpoint metadata points to a missing project root",
        )

    if not _branch_exists(residue.repo_path, residue.branch):
        return CheckpointAnalysis(
            checkpoint=residue,
            task_status=task_status,
            task_title=task_title,
            commits_ahead=0,
            commits_behind=0,
            has_conflicts=False,
            has_uncommitted=False,
            last_commit_age_days=None,
            action=CleanupAction.SAFE_DELETE,
            reason="Checkpoint metadata stale; task branch no longer exists",
        )

    commits_ahead, commits_behind = get_commits_ahead_behind(
        residue.repo_path,
        residue.branch,
        residue.base_branch,
    )
    has_uncommitted = has_uncommitted_changes(residue.repo_path, residue.branch)
    has_conflicts = has_merge_conflicts(residue.repo_path, residue.branch, residue.base_branch)
    last_commit_age = get_last_commit_age_days(residue.repo_path, residue.branch)
    is_merged = is_already_merged(residue.repo_path, residue.branch, residue.base_branch)
    action, reason = _determine_action(
        task_status,
        commits_ahead,
        is_merged,
        has_uncommitted,
        has_conflicts,
    )
    return CheckpointAnalysis(
        checkpoint=residue,
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


def categorize_analysis(analysis: CheckpointAnalysis) -> tuple[str, str]:
    """Return category label and display reason."""
    if analysis.action in (CleanupAction.SAFE_DELETE, CleanupAction.ALREADY_MERGED):
        return "SAFE", analysis.reason
    if analysis.action == CleanupAction.NEEDS_MERGE:
        return "NEEDS_MERGE", analysis.reason
    if analysis.action == CleanupAction.HAS_CONFLICTS:
        return "CONFLICT", analysis.reason
    if analysis.action == CleanupAction.TASK_ACTIVE:
        return "ACTIVE", analysis.reason
    return "REVIEW", analysis.reason


def format_analysis(analysis: CheckpointAnalysis) -> str:
    """Render a compact cleanup analysis line."""
    category, reason = categorize_analysis(analysis)
    branch = analysis.checkpoint.branch
    return f"{analysis.checkpoint.task_id} [{category}] {reason} branch:{branch}"


def _delete_task_family_branches(repo_path: Path, task_id: str, base_branch: str) -> None:
    current_branch = run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_path, check=False)
    if current_branch.returncode == 0 and current_branch.stdout.strip().startswith(f"{task_id}/"):
        run_git(["checkout", base_branch], cwd=repo_path, check=False)

    for branch_info in get_task_branches(task_id, project_id=repo_path.name):
        branch_name = branch_info.get("branch") or ""
        if branch_name:
            run_git(["branch", "-D", branch_name], cwd=repo_path, check=False)


def cleanup_checkpoint(analysis: CheckpointAnalysis, force: bool = False) -> tuple[bool, str]:
    """Remove checkpoint metadata and task-family branches when permitted."""
    if analysis.action == CleanupAction.TASK_ACTIVE and not force:
        return False, "Cannot remove active task checkpoint without --force"
    if analysis.action in (CleanupAction.NEEDS_MERGE, CleanupAction.HAS_CONFLICTS, CleanupAction.MANUAL_REVIEW) and not force:
        return False, f"Checkpoint requires manual review: {analysis.reason}"

    repo_path = analysis.checkpoint.repo_path
    try:
        if repo_path and repo_path.exists():
            _delete_task_family_branches(
                repo_path,
                analysis.checkpoint.task_id,
                analysis.checkpoint.base_branch,
            )
        remove_snapshot(
            analysis.checkpoint.task_id,
            project_id=analysis.checkpoint.project_id,
        )
        return True, f"Removed {analysis.checkpoint.task_id}"
    except Exception as exc:
        return False, f"Error: {exc}"
