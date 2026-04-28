"""Merge operations and orchestration for autonomous tasks."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime

from app.services.task_checkout import get_task_checkout, remove_task_checkout
from app.storage import log_task_event
from app.storage import tasks as task_store
from app.storage.projects import get_project_root_path
from app.storage.tasks.status import update_task_status
from app.storage.tasks.update import update_task_fields

from ....logging_config import get_logger
from ..exec_modules.git_ops import publish_existing_commits
from .git_operations import checkout_base_branch, delete_task_branch, merge_task_branch
from .merge_types import MergeFailed, MergeResult
from .validation import auto_rollback, run_post_merge_validation

logger = get_logger(__name__)
_SNAPSHOT_REF_PREFIX = "refs/summitflow/snapshots/pre-merge/"
_LEGACY_SNAPSHOT_TAG_PREFIX = "snapshot/pre-merge/"


def _err(task_id: str, msg: str) -> MergeResult:
    return {"task_id": task_id, "status": "error", "error": msg}


def _failed(task_id: str, reason: str) -> MergeFailed:
    return {"task_id": task_id, "status": "failed", "reason": reason}


def _git(args: list[str], cwd: str, text: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=text, timeout=10)


def _clear_checkpoint_residue(task_id: str, project_id: str) -> None:
    """Remove checkpoint metadata for a task branch whose checkout state is gone."""
    try:
        from cli.lib.checkpoint import remove_snapshot

        remove_snapshot(task_id, project_id=project_id)
    except Exception as exc:
        logger.warning(
            "checkpoint_residue_cleanup_failed",
            extra={"task_id": task_id, "project_id": project_id, "error": str(exc)},
        )


def _publish_mainline_result(task_id: str, project_root: str, *, phase: str) -> str | None:
    """Publish merged or rolled-back mainline state before cleanup."""
    if publish_existing_commits(project_root):
        return None
    message = f"Auto-merge {phase} not published; main still local-only"
    log_task_event(task_id, message)
    logger.error(
        "auto_merge_publish_failed",
        extra={"task_id": task_id, "project_root": project_root, "phase": phase},
    )
    return message


def _finalize_task_status(
    task_id: str,
    result: MergeResult,
    *,
    complete_task: bool = True,
) -> MergeResult:
    """Persist authoritative task status from merge outcome."""
    status = result.get("status")
    if status in {"merged", "skipped"}:
        if complete_task:
            update_task_status(task_id, "completed", validate_transition=False)
        return result
    if status == "rolled_back":
        # auto_rollback() owns the terminal task status update so it can
        # account for the task's pre-rollback state without double-writing.
        return result
    if status == "failed":
        return result
    if status in {"failed", "error"}:
        update_task_status(
            task_id,
            "failed",
            error_message=str(result.get("reason") or result.get("error") or "merge_cleanup_failed"),
            validate_transition=False,
        )
    return result


def _safe_finalize_branch_without_checkout(task_id: str, project_id: str) -> MergeResult:
    """Best-effort branch cleanup when checkpoint metadata exists without active checkout context."""
    task = task_store.get_task(task_id) or {}
    project_root = get_project_root_path(project_id)
    if not project_root:
        _clear_checkpoint_residue(task_id, project_id)
        return {"task_id": task_id, "status": "skipped", "reason": "no_checkpoint"}

    task_branch = str(task.get("branch_name") or f"{task_id}/main")
    base_branch = str(task.get("base_branch") or "main")
    checkout_error = checkout_base_branch(project_root, base_branch)
    if checkout_error:
        return _err(task_id, checkout_error)

    branch_deleted = delete_task_branch(project_root, task_branch, task_id)
    if branch_deleted:
        _clear_checkpoint_residue(task_id, project_id)
        logger.info(
            "branch_deleted_without_checkout",
            extra={"task_id": task_id, "task_branch": task_branch},
        )
        return {
            "task_id": task_id,
            "status": "merged",
            "task_branch": task_branch,
            "base_branch": base_branch,
            "branch_deleted": True,
            "post_merge_valid": True,
            "post_merge_validation_status": "skipped",
        }
    _clear_checkpoint_residue(task_id, project_id)
    return {
        "task_id": task_id,
        "status": "skipped",
        "reason": "no_checkpoint",
    }


def merge_and_cleanup_task_checkpoint(
    task_id: str,
    project_id: str,
    *,
    complete_task: bool = True,
) -> MergeResult:
    """Merge task branch to main and clear checkpoint state."""
    try:
        if is_task_running(task_id):
            return _finalize_task_status(
                task_id,
                _failed(task_id, "task_still_running"),
                complete_task=complete_task,
            )
        checkout = get_task_checkout(task_id, project_id)
        if not checkout:
            return _finalize_task_status(
                task_id,
                _safe_finalize_branch_without_checkout(task_id, project_id),
                complete_task=complete_task,
            )
        project_root = get_project_root_path(project_id)
        if not project_root:
            return _finalize_task_status(
                task_id,
                _err(task_id, f"No root path for project {project_id}"),
                complete_task=complete_task,
            )

        task_branch = checkout.branch
        base_branch = checkout.base_branch or "main"
        checkout_error = checkout_base_branch(project_root, base_branch)
        if checkout_error:
            return _finalize_task_status(
                task_id,
                _err(task_id, checkout_error),
                complete_task=complete_task,
            )

        _capture_pre_merge_snapshot(task_id, project_root)
        merge_outcome = merge_task_branch(project_root, task_branch, task_id)
        if not merge_outcome.success:
            return _finalize_task_status(
                task_id,
                _build_merge_failure_result(task_id, task_branch, base_branch, merge_outcome),
                complete_task=complete_task,
            )

        if merge_outcome.merge_sha:
            update_task_fields(task_id, merge_sha=merge_outcome.merge_sha)
        logger.info("Merged %s into %s", task_branch, base_branch, extra={"task_id": task_id})
        return _finalize_task_status(
            task_id,
            _complete_merge_cleanup(task_id, project_root, project_id, task_branch, base_branch),
            complete_task=complete_task,
        )

    except subprocess.TimeoutExpired:
        logger.error("Timeout during merge/cleanup for task %s", task_id)
        return _finalize_task_status(
            task_id,
            _err(task_id, "Git operation timed out"),
            complete_task=complete_task,
        )
    except Exception as e:
        logger.error("Error merging/cleaning up task %s: %s", task_id, e)
        return _finalize_task_status(task_id, _err(task_id, str(e)), complete_task=complete_task)


def _capture_pre_merge_snapshot(task_id: str, project_root: str) -> None:
    """Capture HEAD SHA and create an internal pre-merge snapshot ref."""
    result = _git(["git", "rev-parse", "HEAD"], project_root)
    if result.returncode != 0:
        return
    pre_merge_sha = result.stdout.strip()
    _git(["git", "update-ref", f"{_SNAPSHOT_REF_PREFIX}{task_id}", "HEAD"], project_root)
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
    update_task_status(task_id, "failed",
        error_message=f"Merge conflict in {num_conflicts} file(s)", validate_transition=False)
    log_task_event(task_id,
        f"Merge conflict detected in {num_conflicts} file(s): "
        f"{', '.join(merge_outcome.conflicting_files[:5])}")
    logger.warning("Merge conflict for %s", task_branch,
        extra={"task_id": task_id, "conflicting_files": merge_outcome.conflicting_files})
    return {
        "task_id": task_id, "status": "failed",
        "task_branch": task_branch, "base_branch": base_branch,
        "conflicting_files": merge_outcome.conflicting_files,
        "error_output": (merge_outcome.error or "")[:500],
    }


def _complete_merge_cleanup(
    task_id: str, project_root: str, project_id: str, task_branch: str, base_branch: str
) -> MergeResult:
    """Validate and publish mainline state before cleanup removes task residue."""
    validation = run_post_merge_validation(task_id, project_root, project_id)
    if validation["should_rollback"] and auto_rollback(task_id, project_root, project_id, task_branch, validation.get("detail")):
        publish_error = _publish_mainline_result(task_id, project_root, phase="rollback")
        if publish_error:
            return _err(task_id, publish_error)
        remove_task_checkout(task_id, delete_branch=False, project_id=project_id)
        delete_task_branch(project_root, task_branch, task_id)
        _cleanup_old_snapshots(project_root)
        return {
            "task_id": task_id, "status": "rolled_back",
            "task_branch": task_branch, "base_branch": base_branch,
            "reason": "post_merge_validation_failed",
        }
    publish_error = _publish_mainline_result(task_id, project_root, phase="result")
    if publish_error:
        return _err(task_id, publish_error)
    remove_task_checkout(task_id, delete_branch=False, project_id=project_id)
    branch_deleted = delete_task_branch(project_root, task_branch, task_id)
    _cleanup_old_snapshots(project_root)
    return {
        "task_id": task_id, "status": "merged",
        "task_branch": task_branch, "base_branch": base_branch,
        "branch_deleted": branch_deleted,
        "post_merge_valid": validation["passed"],
        "post_merge_validation_status": validation["status"],
    }


def _cleanup_old_snapshots(project_root: str, keep: int = 20) -> None:
    """Remove old internal snapshot refs and any legacy snapshot tags."""
    refs_result = _git(
        ["git", "for-each-ref", "--sort=-creatordate", "--format=%(refname)", _SNAPSHOT_REF_PREFIX],
        project_root,
    )
    if refs_result.returncode == 0:
        refs = [ref.strip() for ref in refs_result.stdout.strip().split("\n") if ref.strip()]
        for old_ref in refs[keep:]:
            _git(["git", "update-ref", "-d", old_ref], project_root, text=False)

    legacy_result = _git(
        ["git", "tag", "-l", f"{_LEGACY_SNAPSHOT_TAG_PREFIX}*", "--sort=-creatordate"],
        project_root,
    )
    if legacy_result.returncode == 0:
        tags = [tag.strip() for tag in legacy_result.stdout.strip().split("\n") if tag.strip()]
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
