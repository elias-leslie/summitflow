"""Merge operations and orchestration for autonomous tasks."""

from __future__ import annotations

import logging
import subprocess
from datetime import UTC, datetime

from app.services.worktree import get_task_worktree, remove_task_worktree
from app.storage import log_task_event
from app.storage import tasks as task_store
from app.storage.projects import get_project_root_path
from app.storage.tasks.status import update_task_status
from app.storage.tasks.update import update_task_fields

from .git_operations import checkout_base_branch, delete_task_branch, merge_task_branch
from .merge_types import MergeResult
from .validation import auto_rollback, run_post_merge_validation

logger = logging.getLogger(__name__)


def _err(task_id: str, msg: str) -> MergeResult:
    return {"task_id": task_id, "status": "error", "error": msg}


def _git(args: list[str], cwd: str, text: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=text, timeout=10)


def _finalize_task_status(task_id: str, result: MergeResult) -> MergeResult:
    """Persist authoritative task status from merge outcome."""
    status = result.get("status")
    if status in {"merged", "skipped"}:
        update_task_status(task_id, "completed", validate_transition=False)
        return result
    if status == "rolled_back":
        update_task_status(
            task_id,
            "failed",
            error_message=str(result.get("reason") or "post_merge_validation_failed"),
            validate_transition=False,
        )
        return result
    if status == "conflicted":
        return result
    if status in {"blocked", "error"}:
        update_task_status(
            task_id,
            "blocked",
            error_message=str(result.get("reason") or result.get("error") or "merge_cleanup_failed"),
            validate_transition=False,
        )
    return result


def _safe_finalize_branch_without_worktree(task_id: str, project_id: str) -> MergeResult:
    """Best-effort branch cleanup when the worktree is already gone.

    This closes the common leak where a task branch is safely deletable but the
    worktree disappeared before finalize-task ran.
    """
    task = task_store.get_task(task_id) or {}
    project_root = get_project_root_path(project_id)
    if not project_root:
        return {"task_id": task_id, "status": "skipped", "reason": "no_worktree"}

    task_branch = str(task.get("branch_name") or f"{task_id}/main")
    base_branch = "main"
    checkout_error = checkout_base_branch(project_root, base_branch)
    if checkout_error:
        return _err(task_id, checkout_error)

    _git(["git", "worktree", "prune"], project_root)
    branch_deleted = delete_task_branch(project_root, task_branch, task_id)
    if branch_deleted:
        logger.info(
            "branch_deleted_without_worktree",
            extra={"task_id": task_id, "task_branch": task_branch},
        )
        return {
            "task_id": task_id,
            "status": "merged",
            "task_branch": task_branch,
            "base_branch": base_branch,
            "branch_deleted": True,
            "post_merge_valid": True,
        }
    return {
        "task_id": task_id,
        "status": "skipped",
        "reason": "no_worktree",
    }


def merge_and_cleanup_task_worktree(task_id: str, project_id: str) -> MergeResult:
    """Merge task branch to main and clean up worktree (auto-approved SIMPLE tasks)."""
    try:
        if is_task_running(task_id):
            return _finalize_task_status(
                task_id,
                {"task_id": task_id, "status": "blocked", "reason": "task_still_running"},
            )
        worktree = get_task_worktree(task_id, project_id)
        if not worktree:
            return _finalize_task_status(
                task_id,
                _safe_finalize_branch_without_worktree(task_id, project_id),
            )
        project_root = get_project_root_path(project_id)
        if not project_root:
            return _finalize_task_status(task_id, _err(task_id, f"No root path for project {project_id}"))

        task_branch = worktree.branch
        base_branch = worktree.base_branch or "main"
        checkout_error = checkout_base_branch(project_root, base_branch)
        if checkout_error:
            return _finalize_task_status(task_id, _err(task_id, checkout_error))

        _capture_pre_merge_snapshot(task_id, project_root)
        merge_outcome = merge_task_branch(project_root, task_branch, task_id)
        if not merge_outcome.success:
            return _finalize_task_status(
                task_id,
                _build_merge_failure_result(task_id, task_branch, base_branch, merge_outcome),
            )

        if merge_outcome.merge_sha:
            update_task_fields(task_id, merge_sha=merge_outcome.merge_sha)
        logger.info("Merged %s into %s", task_branch, base_branch, extra={"task_id": task_id})
        return _finalize_task_status(
            task_id,
            _finalize_merge(task_id, project_root, project_id, task_branch, base_branch),
        )

    except subprocess.TimeoutExpired:
        logger.error("Timeout during merge/cleanup for task %s", task_id)
        return _finalize_task_status(task_id, _err(task_id, "Git operation timed out"))
    except Exception as e:
        logger.error("Error merging/cleaning up task %s: %s", task_id, e)
        return _finalize_task_status(task_id, _err(task_id, str(e)))


def _capture_pre_merge_snapshot(task_id: str, project_root: str) -> None:
    """Capture HEAD SHA and create a pre-merge snapshot tag."""
    result = _git(["git", "rev-parse", "HEAD"], project_root)
    if result.returncode != 0:
        return
    pre_merge_sha = result.stdout.strip()
    _git(["git", "tag", f"snapshot/pre-merge/{task_id}", "HEAD"], project_root)
    update_task_fields(task_id, pre_merge_sha=pre_merge_sha)


def _build_merge_failure_result(
    task_id: str, task_branch: str, base_branch: str, merge_outcome
) -> MergeResult:
    """Build result for a failed merge — conflict or generic error."""
    if not merge_outcome.conflicting_files:
        return _err(task_id, merge_outcome.error or "Unknown merge error")
    num_conflicts = len(merge_outcome.conflicting_files)
    update_task_fields(task_id, conflict_info={
        "conflicting_files": merge_outcome.conflicting_files,
        "task_branch": task_branch, "base_branch": base_branch,
        "detected_at": datetime.now(UTC).isoformat(),
        "error_output": (merge_outcome.error or "")[:500],
    })
    update_task_status(task_id, "conflicted",
        error_message=f"Merge conflict in {num_conflicts} file(s)", validate_transition=False)
    log_task_event(task_id,
        f"Merge conflict detected in {num_conflicts} file(s): "
        f"{', '.join(merge_outcome.conflicting_files[:5])}")
    logger.warning("Merge conflict for %s", task_branch,
        extra={"task_id": task_id, "conflicting_files": merge_outcome.conflicting_files})
    return {
        "task_id": task_id, "status": "conflicted",
        "task_branch": task_branch, "base_branch": base_branch,
        "conflicting_files": merge_outcome.conflicting_files,
        "error_output": (merge_outcome.error or "")[:500],
    }


def _finalize_merge(
    task_id: str, project_root: str, project_id: str, task_branch: str, base_branch: str
) -> MergeResult:
    """Remove worktree, delete branch, run post-merge validation, clean up snapshots."""
    remove_task_worktree(task_id, delete_branch=False, project_id=project_id)
    _git(["git", "worktree", "prune"], project_root)
    branch_deleted = delete_task_branch(project_root, task_branch, task_id)
    validation_passed = run_post_merge_validation(task_id, project_root, project_id)
    if not validation_passed and auto_rollback(task_id, project_root, project_id, task_branch):
        return {
            "task_id": task_id, "status": "rolled_back",
            "task_branch": task_branch, "base_branch": base_branch,
            "reason": "post_merge_validation_failed",
        }
    _cleanup_old_snapshots(project_root)
    return {
        "task_id": task_id, "status": "merged",
        "task_branch": task_branch, "base_branch": base_branch,
        "branch_deleted": branch_deleted, "post_merge_valid": validation_passed,
    }


def _cleanup_old_snapshots(project_root: str, keep: int = 20) -> None:
    """Remove old snapshot tags, keeping the most recent `keep` tags."""
    result = _git(["git", "tag", "-l", "snapshot/pre-merge/*", "--sort=-creatordate"], project_root)
    if result.returncode != 0:
        return
    tags = [t.strip() for t in result.stdout.strip().split("\n") if t.strip()]
    for old_tag in tags[keep:]:
        _git(["git", "tag", "-d", old_tag], project_root, text=False)


def is_task_running(task_id: str) -> bool:
    """Check if task is still running."""
    task = task_store.get_task(task_id)
    running = bool(task and task.get("status") == "running")
    if running:
        logger.warning("merge_blocked_task_running", extra={"task_id": task_id})
    return running


# Re-export internal functions for backward compatibility
_auto_rollback = auto_rollback
_run_post_merge_validation = run_post_merge_validation
