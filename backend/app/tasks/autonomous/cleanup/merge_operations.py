"""Merge operations and orchestration for autonomous tasks."""

from __future__ import annotations

import subprocess
from typing import Any

from app.services.task_checkout import get_task_checkout, remove_task_checkout
from app.storage import log_task_event
from app.storage import tasks as task_store
from app.storage.projects import get_project_root_path
from app.storage.tasks.status import update_task_status
from app.storage.tasks.update import update_task_fields
from app.utils.git_base import normalize_base_branch

from ....logging_config import get_logger
from ..exec_modules.git_ops import publish_existing_commits
from .git_operations import checkout_base_branch, delete_task_branch, merge_task_branch
from .merge_operations_impl import (
    build_merge_failure_result_impl,
    capture_pre_merge_snapshot_impl,
    cleanup_old_snapshots_impl,
    complete_merge_cleanup_impl,
    err_result,
    failed_result,
    finalize_task_status_impl,
    merge_and_cleanup_task_checkpoint_impl,
    safe_finalize_branch_without_checkout_impl,
)
from .merge_types import MergeFailed, MergeResult

logger = get_logger(__name__)
_SNAPSHOT_REF_PREFIX = "refs/summitflow/snapshots/pre-merge/"
_LEGACY_SNAPSHOT_TAG_PREFIX = "snapshot/pre-merge/"


def _err(task_id: str, msg: str) -> MergeResult:
    return err_result(task_id, msg)


def _failed(task_id: str, reason: str) -> MergeFailed:
    return failed_result(task_id, reason)


def _git(args: list[str], cwd: str, text: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=text, timeout=10)


def _clear_checkpoint_residue(task_id: str, project_id: str) -> None:
    try:
        from cli.lib.checkpoint import remove_snapshot

        remove_snapshot(task_id, project_id=project_id)
    except Exception as exc:
        logger.warning(
            "checkpoint_residue_cleanup_failed",
            extra={"task_id": task_id, "project_id": project_id, "error": str(exc)},
        )


def _publish_mainline_result(task_id: str, project_root: str, *, phase: str) -> str | None:
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
    return finalize_task_status_impl(
        task_id,
        result,
        complete_task=complete_task,
        update_task_status=update_task_status,
    )


def _safe_finalize_branch_without_checkout(task_id: str, project_id: str) -> MergeResult:
    return safe_finalize_branch_without_checkout_impl(task_id, project_id, _merge_deps())


def merge_and_cleanup_task_checkpoint(
    task_id: str,
    project_id: str,
    *,
    complete_task: bool = True,
) -> MergeResult:
    return merge_and_cleanup_task_checkpoint_impl(
        task_id,
        project_id,
        complete_task=complete_task,
        deps=_merge_deps(),
    )


def _capture_pre_merge_snapshot(task_id: str, project_root: str) -> None:
    capture_pre_merge_snapshot_impl(task_id, project_root, _merge_deps())


def _build_merge_failure_result(
    task_id: str, task_branch: str, base_branch: str, merge_outcome: Any
) -> MergeResult:
    return build_merge_failure_result_impl(
        task_id, task_branch, base_branch, merge_outcome, _merge_deps()
    )


def _complete_merge_cleanup(
    task_id: str, project_root: str, project_id: str, task_branch: str, base_branch: str
) -> MergeResult:
    return complete_merge_cleanup_impl(
        task_id, project_root, project_id, task_branch, base_branch, _merge_deps()
    )


def _cleanup_old_snapshots(project_root: str, keep: int = 20) -> None:
    cleanup_old_snapshots_impl(project_root, keep=keep, deps=_merge_deps())


def is_task_running(task_id: str) -> bool:
    task = task_store.get_task(task_id)
    running = bool(task and task.get("status") == "running")
    if running:
        logger.warning("merge_blocked_task_running", extra={"task_id": task_id})
    return running


def _merge_deps() -> dict[str, Any]:
    return {
        "build_merge_failure_result": _build_merge_failure_result,
        "capture_pre_merge_snapshot": _capture_pre_merge_snapshot,
        "checkout_base_branch": checkout_base_branch,
        "cleanup_old_snapshots": _cleanup_old_snapshots,
        "clear_checkpoint_residue": _clear_checkpoint_residue,
        "complete_merge_cleanup": _complete_merge_cleanup,
        "delete_task_branch": delete_task_branch,
        "err": _err,
        "failed": _failed,
        "finalize_task_status": _finalize_task_status,
        "get_project_root_path": get_project_root_path,
        "get_task_checkout": get_task_checkout,
        "git": _git,
        "is_task_running": is_task_running,
        "legacy_snapshot_tag_prefix": _LEGACY_SNAPSHOT_TAG_PREFIX,
        "log_task_event": log_task_event,
        "logger": logger,
        "merge_task_branch": merge_task_branch,
        "normalize_base_branch": normalize_base_branch,
        "publish_mainline_result": _publish_mainline_result,
        "remove_task_checkout": remove_task_checkout,
        "safe_finalize_branch_without_checkout": _safe_finalize_branch_without_checkout,
        "snapshot_ref_prefix": _SNAPSHOT_REF_PREFIX,
        "task_store": task_store,
        "update_task_fields": update_task_fields,
        "update_task_status": update_task_status,
    }
