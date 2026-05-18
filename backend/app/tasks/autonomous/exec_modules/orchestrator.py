from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ....core.debug import debug_section
from ....logging_config import get_logger
from ....services.task_checkout import get_task_checkout
from ....storage import tasks as task_store
from .checkout import check_main_repo_leakage
from .checkout_setup import setup_task_checkout
from .completion_handler import (
    handle_early_completion,
    handle_failed_execution,
    handle_successful_completion,
)
from .events import emit_error, emit_log, emit_progress
from .execution_loop import execute_subtask_loop
from .orchestrator_execution import execute_task_locked_impl, handle_completion, load_subtasks
from .pristine_validation import validate_pristine_codebase

logger = get_logger(__name__)


def prepare_execution(
    task_id: str,
    project_id: str,
    *,
    task_store: Any,
    emit_error: Callable[..., None],
    validate_pristine_codebase: Callable[[str, str], bool],
    setup_task_checkout: Callable[[str, str], str | None],
) -> tuple[dict[str, Any] | None, str | None, str | None, str | None]:
    """Validate task and set up shared checkout."""
    task = task_store.get_task(task_id)
    if not task:
        emit_error(task_id, "Task not found", recoverable=False, project_id=project_id)
        return {"task_id": task_id, "status": "error", "message": "Task not found"}, None, None, None

    if not validate_pristine_codebase(task_id, project_id):
        return _setup_failed_result(task_id, "Blocked by baseline quality gate", "quality_gate_blocked"), None, None, None

    project_path = setup_task_checkout(task_id, project_id)
    if not project_path:
        return _setup_failed_result(task_id, "Task branch setup failed", "task_branch_setup_failed"), None, None, None

    return None, project_path, task.get("task_type"), task.get("agent_override")


def active_task_checkpoint(task_id: str, project_id: str, *, load_snapshot_meta: Callable[[str], Any]) -> bool:
    """Return whether task still has active checkpoint metadata to clean up."""
    meta = load_snapshot_meta(task_id)
    return meta is not None and meta.project_id == project_id


def prepare_completed_task_closeout(
    task_id: str,
    project_id: str,
    *,
    validate_pristine_codebase: Callable[[str, str], bool],
    has_active_task_checkpoint: Callable[[str, str], bool],
    get_task_checkout: Callable[[str, str], Any],
    setup_task_checkout: Callable[[str, str], str | None],
    emit_log: Callable[..., None],
) -> dict[str, Any] | None:
    """Run safety checks before early-completing a task whose subtasks already passed."""
    if not validate_pristine_codebase(task_id, project_id):
        return _setup_failed_result(task_id, "Blocked by baseline quality gate", "quality_gate_blocked")

    if not has_active_task_checkpoint(task_id, project_id):
        emit_log(task_id, "info", "All subtasks already complete; skipping checkout setup", project_id=project_id)
        return None

    if not get_task_checkout(task_id, project_id):
        emit_log(
            task_id,
            "warning",
            "All subtasks already complete; active checkpoint metadata remains but no task branch exists, skipping checkout recovery",
            project_id=project_id,
        )
        return None

    emit_log(
        task_id,
        "info",
        "All subtasks already complete; reusing existing task branch to recover residue before closeout",
        project_id=project_id,
    )
    if setup_task_checkout(task_id, project_id):
        return None
    return _setup_failed_result(task_id, "Task branch setup failed", "task_branch_setup_failed")


def _setup_failed_result(task_id: str, error: str, reason: str) -> dict[str, Any]:
    return {"task_id": task_id, "status": "failed", "error": error, "reason": reason}


def start_execution(
    task_id: str,
    project_id: str,
    dispatch: Callable[[str, str, str], None] | None = None,
) -> dict[str, Any]:
    debug_section("Autonomous Execution", task_id=task_id, project_id=project_id)
    logger.info("Starting autonomous execution", task_id=task_id, project_id=project_id)
    emit_log(task_id, "info", "Starting autonomous execution", project_id=project_id)
    return execute_task_locked(task_id, project_id, dispatch=dispatch)


def _prepare_execution(task_id: str, project_id: str) -> tuple[dict[str, Any] | None, str | None, str | None, str | None]:
    return prepare_execution(
        task_id,
        project_id,
        task_store=task_store,
        emit_error=emit_error,
        validate_pristine_codebase=validate_pristine_codebase,
        setup_task_checkout=setup_task_checkout,
    )


def _has_active_task_checkpoint(task_id: str, project_id: str) -> bool:
    from cli.lib.checkpoint_metadata import load_snapshot_meta

    return active_task_checkpoint(task_id, project_id, load_snapshot_meta=load_snapshot_meta)


def _prepare_completed_task_closeout(task_id: str, project_id: str) -> dict[str, Any] | None:
    return prepare_completed_task_closeout(
        task_id,
        project_id,
        validate_pristine_codebase=validate_pristine_codebase,
        has_active_task_checkpoint=_has_active_task_checkpoint,
        get_task_checkout=get_task_checkout,
        setup_task_checkout=setup_task_checkout,
        emit_log=emit_log,
    )


def execute_task_locked(
    task_id: str,
    project_id: str,
    dispatch: Callable[[str, str, str], None] | None = None,
) -> dict[str, Any]:
    return execute_task_locked_impl(task_id, project_id, dispatch, deps=_execution_deps())


def _execution_deps() -> dict[str, Any]:
    return {
        "task_store": task_store,
        "emit_error": emit_error,
        "emit_log": emit_log,
        "load_subtasks": _load_subtasks_with_deps,
        "prepare_completed_task_closeout": _prepare_completed_task_closeout,
        "handle_early_completion": handle_early_completion,
        "prepare_execution": _prepare_execution,
        "execute_subtask_loop": execute_subtask_loop,
        "check_main_repo_leakage": check_main_repo_leakage,
        "handle_completion": _handle_completion_with_deps,
    }


def _load_subtasks_with_deps(task_id: str, project_id: str) -> tuple[dict[str, Any] | None, list, int, int]:
    return load_subtasks(
        task_id,
        project_id,
        emit_progress=emit_progress,
        emit_error=emit_error,
        task_store=task_store,
    )


def _handle_completion_with_deps(
    task_id: str,
    project_id: str,
    project_path: str,
    results: list,
    incomplete: list,
    dispatch: Callable[[str, str, str], None] | None,
    wind_down_state: Any,
) -> str | None:
    return handle_completion(
        task_id,
        project_id,
        project_path,
        results,
        incomplete,
        dispatch,
        wind_down_state,
        handle_successful_completion=handle_successful_completion,
        handle_failed_execution=handle_failed_execution,
    )
