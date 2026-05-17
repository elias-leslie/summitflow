"""Post-merge validation and auto-rollback operations."""

from __future__ import annotations

import subprocess
from typing import Literal, TypedDict

from app.storage import tasks as task_store
from app.storage.agent_configs_quality import build_st_check_command

from ....logging_config import get_logger
from ..exec_modules.quality_utils import find_check_tool
from .git_operations import revert_merge_commit

logger = get_logger(__name__)


class PostMergeValidationResult(TypedDict):
    """Outcome of post-merge validation."""

    status: Literal["passed", "failed", "timed_out", "skipped", "error"]
    passed: bool
    should_rollback: bool
    detail: str | None


def _skipped_result(detail: str) -> PostMergeValidationResult:
    return {"status": "skipped", "passed": True, "should_rollback": False, "detail": detail}


def _error_result(detail: str) -> PostMergeValidationResult:
    return {"status": "error", "passed": False, "should_rollback": False, "detail": detail}


def _timeout_result() -> PostMergeValidationResult:
    return {
        "status": "timed_out",
        "passed": False,
        "should_rollback": False,
        "detail": "validation timed out after 120s",
    }


def _log_validation_failure(task_id: str, output: str) -> None:
    from app.storage import log_task_event

    log_task_event(task_id, f"Post-merge validation: FAILED\n{output}")
    logger.warning(
        "Post-merge validation failed",
        extra={"task_id": task_id, "output": output[:200]},
    )


def _log_validation_skip(task_id: str, reason: str) -> None:
    from app.storage import log_task_event

    log_task_event(task_id, f"Post-merge validation: SKIPPED - {reason}")
    logger.warning(
        "Post-merge validation skipped",
        extra={"task_id": task_id, "reason": reason},
    )


def _resolve_check_command(project_id: str) -> list[str] | None:
    st_cmd = find_check_tool()
    if not st_cmd:
        return None
    return build_st_check_command(st_cmd, project_id)


def _run_check_quick(
    project_root: str,
    task_id: str,
    project_id: str,
) -> PostMergeValidationResult:
    from app.storage import log_task_event

    cmd = _resolve_check_command(project_id)
    if not cmd:
        _log_validation_skip(task_id, "st check not available")
        return _skipped_result("st check not available")

    result = subprocess.run(
        cmd,
        cwd=project_root,
        capture_output=True,
        text=True,
        timeout=120,
    )

    if result.returncode == 0:
        log_task_event(task_id, "Post-merge validation: PASSED")
        logger.info("Post-merge validation passed", extra={"task_id": task_id})
        return {"status": "passed", "passed": True, "should_rollback": False, "detail": None}

    output = (result.stdout + result.stderr)[-500:]
    _log_validation_failure(task_id, output)
    return {"status": "failed", "passed": False, "should_rollback": True, "detail": output}


def run_post_merge_validation(
    task_id: str,
    project_root: str,
    project_id: str,
) -> PostMergeValidationResult:
    from app.storage import log_task_event

    try:
        return _run_check_quick(project_root, task_id, project_id)
    except subprocess.TimeoutExpired:
        log_task_event(task_id, "Post-merge validation: TIMEOUT (120s)")
        logger.warning("Post-merge validation timed out", extra={"task_id": task_id})
        return _timeout_result()
    except FileNotFoundError as exc:
        _log_validation_skip(task_id, f"validation tool missing ({exc})")
        return _skipped_result(f"validation tool missing ({exc})")
    except Exception as exc:
        log_task_event(task_id, f"Post-merge validation: ERROR - {exc}")
        logger.warning(
            "Post-merge validation error",
            extra={"task_id": task_id, "error": str(exc)},
        )
        return _error_result(str(exc))


def _get_head_commit(project_root: str) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=project_root,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _get_merge_affected_files(project_root: str, merge_commit: str) -> list[str]:
    result = subprocess.run(
        ["git", "diff-tree", "--no-commit-id", "-r", "--name-only", merge_commit],
        cwd=project_root,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.strip().splitlines() if line.strip()][:10]


def _apply_rollback_side_effects(
    task_id: str,
    project_id: str,
    task_branch: str,
    *,
    failure_detail: str | None = None,
    merge_commit: str | None = None,
    affected_files: list[str] | None = None,
) -> None:
    from app.storage import log_task_event

    log_task_event(
        task_id,
        f"Auto-rollback: Reverted merge of {task_branch} due to regression",
    )
    logger.info(
        "Auto-rollback succeeded",
        extra={"task_id": task_id, "task_branch": task_branch},
    )
    create_regression_fix_task(
        task_id,
        project_id,
        task_branch,
        failure_detail=failure_detail,
        merge_commit=merge_commit,
        affected_files=affected_files,
    )
    task = task_store.get_task(task_id) or {}
    if task.get("status") == "completed":
        task_store.update_task_status(task_id, "failed", validate_transition=False)
    else:
        task_store.update_task_status(task_id, "failed")
    save_rollback_learning(task_id, project_id, task_branch)


def auto_rollback(
    task_id: str,
    project_root: str,
    project_id: str,
    task_branch: str,
    failure_detail: str | None = None,
) -> bool:
    from app.storage import log_task_event

    try:
        merge_commit = _get_head_commit(project_root)
        if not revert_merge_commit(task_id, project_root):
            return False
        affected_files = (
            _get_merge_affected_files(project_root, merge_commit) if merge_commit else None
        )
        _apply_rollback_side_effects(
            task_id,
            project_id,
            task_branch,
            failure_detail=failure_detail,
            merge_commit=merge_commit,
            affected_files=affected_files,
        )
        return True
    except subprocess.TimeoutExpired:
        log_task_event(task_id, "Auto-rollback: git revert timed out")
        return False
    except Exception as exc:
        log_task_event(task_id, f"Auto-rollback ERROR: {exc}")
        logger.error(
            "Auto-rollback error",
            extra={"task_id": task_id, "error": str(exc)},
        )
        return False


def _create_regression_subtasks(
    task_id: str,
    task_branch: str,
    failure_detail: str | None,
) -> None:
    from app.storage.subtasks_create import create_subtask

    fail_hint = f": {failure_detail[:120].strip()}" if failure_detail else ""
    subtasks = [
        (
            "1.1",
            f"Reproduce failure: run `st check --quick` and confirm the same error{fail_hint}",
            0,
            "backend",
        ),
        ("1.2", f"Fix the root cause in {task_branch} that broke validation", 1, "backend"),
        (
            "1.3",
            "Verify fix: run `st check --quick`, confirm exit 0, then re-dispatch via autocode",
            2,
            "test",
        ),
    ]
    for subtask_id, description, order, subtask_type in subtasks:
        try:
            create_subtask(task_id, subtask_id, description, order, subtask_type=subtask_type)
        except Exception as exc:
            logger.warning(
                "Failed to create regression subtask",
                extra={"task_id": task_id, "subtask_id": subtask_id, "error": str(exc)},
            )


def _build_regression_description(
    task_id: str,
    task_branch: str,
    failure_detail: str | None,
    merge_commit: str | None,
    affected_files: list[str] | None,
) -> str:
    parts = [
        f"Auto-rollback triggered: merge of task {task_id} (branch {task_branch}) caused post-merge validation failure. The merge has been reverted."
    ]
    if merge_commit:
        parts.append(f"Reverted merge commit: {merge_commit}")
    if affected_files:
        files_str = "\n".join(f"  - {path}" for path in affected_files)
        parts.append(f"Files changed in rolled-back merge:\n{files_str}")
    if failure_detail:
        parts.append(f"Validation failure output:\n{failure_detail[:400].strip()}")
    return "\n\n".join(parts)


def _finalize_regression_task(new_task_id: str, task_branch: str, failure_detail: str | None) -> None:
    from app.storage.task_spirit import update_task_spirit

    done_when = [
        "Run `st check --quick` — all checks pass (exit 0)",
        "Root cause of the validation failure is identified and fixed",
        "Fix is re-merged to main without triggering another rollback",
    ]
    try:
        update_task_spirit(new_task_id, done_when=done_when)
    except Exception as exc:
        logger.warning(
            "Failed to set done_when on regression task",
            extra={"task_id": new_task_id, "error": str(exc)},
        )
    _create_regression_subtasks(new_task_id, task_branch, failure_detail)


def create_regression_fix_task(
    task_id: str,
    project_id: str,
    task_branch: str,
    failure_detail: str | None = None,
    merge_commit: str | None = None,
    affected_files: list[str] | None = None,
) -> None:
    from app.storage.tasks.core import create_task

    description = _build_regression_description(
        task_id, task_branch, failure_detail, merge_commit, affected_files
    )
    try:
        task = create_task(
            project_id=project_id,
            title=f"Fix: regression from {task_id} ({task_branch})",
            description=description,
            task_type="regression",
            priority=1,
            parent_task_id=task_id,
            execution_mode="autonomous",
            labels=["regression", "rollback"],
        )
    except Exception as exc:
        logger.warning(
            "Failed to create regression fix task",
            extra={"task_id": task_id, "error": str(exc)},
        )
        return

    _finalize_regression_task(task["id"], task_branch, failure_detail)


def save_rollback_learning(
    task_id: str,
    project_id: str,
    task_branch: str,
) -> None:
    """Save rollback pattern to memory system."""
