from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ....core.debug import debug_section
from ....logging_config import get_logger
from ....storage import tasks as task_store
from .checkout import get_project_path
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
) -> tuple[dict[str, Any] | None, str | None, str | None, str | None]:
    """Validate task and resolve project root."""
    task = task_store.get_task(task_id)
    if not task:
        emit_error(task_id, "Task not found", recoverable=False, project_id=project_id)
        return {"task_id": task_id, "status": "error", "message": "Task not found"}, None, None, None

    if not validate_pristine_codebase(task_id, project_id):
        return _setup_failed_result(task_id, "Blocked by baseline quality gate", "quality_gate_blocked"), None, None, None

    try:
        project_path = get_project_path(project_id)
    except ValueError as exc:
        emit_error(task_id, str(exc), recoverable=False, project_id=project_id)
        return _setup_failed_result(task_id, str(exc), "project_root_missing"), None, None, None

    return None, project_path, task.get("task_type"), task.get("agent_override")


def prepare_completed_task_closeout(
    task_id: str,
    project_id: str,
    *,
    validate_pristine_codebase: Callable[[str, str], bool],
    emit_log: Callable[..., None],
) -> dict[str, Any] | None:
    """Run safety checks before early-completing a task whose subtasks already passed."""
    if not validate_pristine_codebase(task_id, project_id):
        return _setup_failed_result(task_id, "Blocked by baseline quality gate", "quality_gate_blocked")
    emit_log(task_id, "info", "All subtasks already complete; nothing to set up", project_id=project_id)
    return None


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
    )


def _prepare_completed_task_closeout(task_id: str, project_id: str) -> dict[str, Any] | None:
    return prepare_completed_task_closeout(
        task_id,
        project_id,
        validate_pristine_codebase=validate_pristine_codebase,
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
