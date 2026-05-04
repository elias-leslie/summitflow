"""Implementation helpers for autonomous task merge cleanup."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from typing import Any

from .merge_types import MergeFailed, MergeResult


def err_result(task_id: str, msg: str) -> MergeResult:
    return {"task_id": task_id, "status": "error", "error": msg}


def failed_result(task_id: str, reason: str) -> MergeFailed:
    return {"task_id": task_id, "status": "failed", "reason": reason}


def finalize_task_status_impl(
    task_id: str,
    result: MergeResult,
    *,
    complete_task: bool,
    update_task_status: Any,
) -> MergeResult:
    status = result.get("status")
    if status in {"merged", "skipped"}:
        if complete_task:
            update_task_status(task_id, "completed", validate_transition=False)
        return result
    if status == "rolled_back":
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


def safe_finalize_branch_without_checkout_impl(
    task_id: str,
    project_id: str,
    deps: dict[str, Any],
) -> MergeResult:
    task = deps["task_store"].get_task(task_id) or {}
    project_root = deps["get_project_root_path"](project_id)
    if not project_root:
        deps["clear_checkpoint_residue"](task_id, project_id)
        return {"task_id": task_id, "status": "skipped", "reason": "no_checkpoint"}

    task_branch = str(task.get("branch_name") or f"{task_id}/main")
    base_branch = deps["normalize_base_branch"](
        str(task.get("base_branch") or "main"), project_root
    )
    checkout_error = deps["checkout_base_branch"](project_root, base_branch)
    if checkout_error:
        return deps["err"](task_id, checkout_error)

    branch_deleted = deps["delete_task_branch"](project_root, task_branch, task_id)
    deps["clear_checkpoint_residue"](task_id, project_id)
    if not branch_deleted:
        return {"task_id": task_id, "status": "skipped", "reason": "no_checkpoint"}
    deps["logger"].info(
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


def merge_and_cleanup_task_checkpoint_impl(
    task_id: str,
    project_id: str,
    *,
    complete_task: bool,
    deps: dict[str, Any],
) -> MergeResult:
    finalize = deps["finalize_task_status"]
    try:
        result = _merge_task_checkpoint(task_id, project_id, deps)
        return finalize(task_id, result, complete_task=complete_task)
    except subprocess.TimeoutExpired:
        deps["logger"].error("Timeout during merge/cleanup for task %s", task_id)
        return finalize(
            task_id, deps["err"](task_id, "Git operation timed out"), complete_task=complete_task
        )
    except Exception as exc:
        deps["logger"].error("Error merging/cleaning up task %s: %s", task_id, exc)
        return finalize(task_id, deps["err"](task_id, str(exc)), complete_task=complete_task)


def _merge_task_checkpoint(task_id: str, project_id: str, deps: dict[str, Any]) -> MergeResult:
    if deps["is_task_running"](task_id):
        return deps["failed"](task_id, "task_still_running")

    checkout = deps["get_task_checkout"](task_id, project_id)
    if not checkout:
        return deps["safe_finalize_branch_without_checkout"](task_id, project_id)

    project_root = deps["get_project_root_path"](project_id)
    if not project_root:
        return deps["err"](task_id, f"No root path for project {project_id}")

    task_branch = checkout.branch
    base_branch = deps["normalize_base_branch"](checkout.base_branch or "main", project_root)
    checkout_error = deps["checkout_base_branch"](project_root, base_branch)
    if checkout_error:
        return deps["err"](task_id, checkout_error)

    return _merge_checked_out_branch(task_id, project_id, project_root, task_branch, base_branch, deps)


def _merge_checked_out_branch(
    task_id: str,
    project_id: str,
    project_root: str,
    task_branch: str,
    base_branch: str,
    deps: dict[str, Any],
) -> MergeResult:
    deps["capture_pre_merge_snapshot"](task_id, project_root)
    merge_outcome = deps["merge_task_branch"](project_root, task_branch, task_id)
    if not merge_outcome.success:
        return deps["build_merge_failure_result"](task_id, task_branch, base_branch, merge_outcome)

    if merge_outcome.merge_sha:
        deps["update_task_fields"](task_id, merge_sha=merge_outcome.merge_sha)
    deps["logger"].info("Merged %s into %s", task_branch, base_branch, extra={"task_id": task_id})
    return deps["complete_merge_cleanup"](
        task_id, project_root, project_id, task_branch, base_branch
    )


def capture_pre_merge_snapshot_impl(task_id: str, project_root: str, deps: dict[str, Any]) -> None:
    result = deps["git"](["git", "rev-parse", "HEAD"], project_root)
    if result.returncode != 0:
        return
    pre_merge_sha = result.stdout.strip()
    deps["git"](["git", "update-ref", f"{deps['snapshot_ref_prefix']}{task_id}", "HEAD"], project_root)
    deps["update_task_fields"](task_id, pre_merge_sha=pre_merge_sha)


def build_merge_failure_result_impl(
    task_id: str, task_branch: str, base_branch: str, merge_outcome: Any, deps: dict[str, Any]
) -> MergeResult:
    if not merge_outcome.conflicting_files:
        return deps["err"](task_id, merge_outcome.error or "Unknown merge error")
    num_conflicts = len(merge_outcome.conflicting_files)
    deps["update_task_fields"](task_id, conflict_info=_conflict_info(merge_outcome, task_branch, base_branch))
    deps["update_task_status"](
        task_id,
        "failed",
        error_message=f"Merge conflict in {num_conflicts} file(s)",
        validate_transition=False,
    )
    deps["log_task_event"](task_id, _conflict_event(num_conflicts, merge_outcome.conflicting_files))
    deps["logger"].warning(
        "Merge conflict for %s",
        task_branch,
        extra={"task_id": task_id, "conflicting_files": merge_outcome.conflicting_files},
    )
    return _conflict_result(task_id, task_branch, base_branch, merge_outcome)


def _conflict_info(merge_outcome: Any, task_branch: str, base_branch: str) -> dict[str, Any]:
    return {
        "conflicting_files": merge_outcome.conflicting_files,
        "task_branch": task_branch,
        "base_branch": base_branch,
        "detected_at": datetime.now(UTC).isoformat(),
        "error_output": (merge_outcome.error or "")[:500],
    }


def _conflict_event(num_conflicts: int, conflicting_files: list[str]) -> str:
    return (
        f"Merge conflict detected in {num_conflicts} file(s): "
        f"{', '.join(conflicting_files[:5])}"
    )


def _conflict_result(
    task_id: str, task_branch: str, base_branch: str, merge_outcome: Any
) -> MergeResult:
    return {
        "task_id": task_id,
        "status": "failed",
        "task_branch": task_branch,
        "base_branch": base_branch,
        "conflicting_files": merge_outcome.conflicting_files,
        "error_output": (merge_outcome.error or "")[:500],
    }


def complete_merge_cleanup_impl(
    task_id: str,
    project_root: str,
    project_id: str,
    task_branch: str,
    base_branch: str,
    deps: dict[str, Any],
) -> MergeResult:
    validation = deps["run_post_merge_validation"](task_id, project_root, project_id)
    if validation["should_rollback"] and deps["auto_rollback"](
        task_id, project_root, project_id, task_branch, validation.get("detail")
    ):
        return _complete_rollback(task_id, project_root, project_id, task_branch, base_branch, deps)
    publish_error = deps["publish_mainline_result"](task_id, project_root, phase="result")
    if publish_error:
        return deps["err"](task_id, publish_error)
    deps["remove_task_checkout"](task_id, delete_branch=False, project_id=project_id)
    branch_deleted = deps["delete_task_branch"](project_root, task_branch, task_id)
    deps["cleanup_old_snapshots"](project_root)
    return {
        "task_id": task_id,
        "status": "merged",
        "task_branch": task_branch,
        "base_branch": base_branch,
        "branch_deleted": branch_deleted,
        "post_merge_valid": validation["passed"],
        "post_merge_validation_status": validation["status"],
    }


def _complete_rollback(
    task_id: str,
    project_root: str,
    project_id: str,
    task_branch: str,
    base_branch: str,
    deps: dict[str, Any],
) -> MergeResult:
    publish_error = deps["publish_mainline_result"](task_id, project_root, phase="rollback")
    if publish_error:
        return deps["err"](task_id, publish_error)
    deps["remove_task_checkout"](task_id, delete_branch=False, project_id=project_id)
    deps["delete_task_branch"](project_root, task_branch, task_id)
    deps["cleanup_old_snapshots"](project_root)
    return {
        "task_id": task_id,
        "status": "rolled_back",
        "task_branch": task_branch,
        "base_branch": base_branch,
        "reason": "post_merge_validation_failed",
    }


def cleanup_old_snapshots_impl(project_root: str, *, keep: int, deps: dict[str, Any]) -> None:
    _cleanup_snapshot_refs(project_root, keep, deps)
    _cleanup_legacy_snapshot_tags(project_root, keep, deps)


def _cleanup_snapshot_refs(project_root: str, keep: int, deps: dict[str, Any]) -> None:
    refs_result = deps["git"](
        ["git", "for-each-ref", "--sort=-creatordate", "--format=%(refname)", deps["snapshot_ref_prefix"]],
        project_root,
    )
    if refs_result.returncode != 0:
        return
    refs = [ref.strip() for ref in refs_result.stdout.strip().split("\n") if ref.strip()]
    for old_ref in refs[keep:]:
        deps["git"](["git", "update-ref", "-d", old_ref], project_root, text=False)


def _cleanup_legacy_snapshot_tags(project_root: str, keep: int, deps: dict[str, Any]) -> None:
    legacy_result = deps["git"](
        ["git", "tag", "-l", f"{deps['legacy_snapshot_tag_prefix']}*", "--sort=-creatordate"],
        project_root,
    )
    if legacy_result.returncode != 0:
        return
    tags = [tag.strip() for tag in legacy_result.stdout.strip().split("\n") if tag.strip()]
    for old_tag in tags[keep:]:
        deps["git"](["git", "tag", "-d", old_tag], project_root, text=False)
