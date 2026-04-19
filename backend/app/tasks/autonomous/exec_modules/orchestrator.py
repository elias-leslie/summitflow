"""Main task orchestration and execution flow."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ....core.debug import debug_section
from ....logging_config import get_logger
from ....services.task_checkout import get_task_checkout
from ....services.task_lane_preflight import check_task_lane_conflicts
from ....storage import tasks as task_store
from ....storage.subtasks import get_subtasks_for_task
from .agent_execution import execute_agent_feedback
from .checkout import check_main_repo_leakage
from .checkout_setup import setup_task_checkout
from .completion_handler import (
    handle_early_completion,
    handle_failed_execution,
    handle_partial_completion,
    handle_successful_completion,
)
from .events import emit_error, emit_log, emit_progress
from .execution_loop import execute_subtask_loop
from .pristine_validation import validate_pristine_codebase

logger = get_logger(__name__)


def _guard_existing_same_task_lane(task_id: str, project_id: str) -> dict[str, Any] | None:
    """Avoid replaying the same task when an active live session already exists."""
    lane_check = check_task_lane_conflicts(task_id, project_id)
    if lane_check.overlap_kind != "same_task" or lane_check.disposition != "block":
        return None

    owner = lane_check.owner_session_id or "unknown"
    emit_log(
        task_id,
        "info",
        f"Execution skipped: active task session already owned by session {owner}",
        project_id=project_id,
    )
    logger.info(
        "Skipping duplicate autonomous execution for active task session",
        task_id=task_id,
        project_id=project_id,
        owner_session_id=lane_check.owner_session_id,
        owner_location=lane_check.owner_location,
    )
    return {
        "task_id": task_id,
        "status": "already_running",
        "message": "Active task session already exists",
        "owner_session_id": lane_check.owner_session_id,
    }


def start_execution(
    task_id: str,
    project_id: str,
    dispatch: Callable[[str, str, str], None] | None = None,
) -> dict[str, Any]:
    """Start autonomous execution of a task.

    Executes subtasks in order with fresh context per subtask, using
    complete() with execute_tools=True. Concurrency handled by Hatchet
    ConcurrencyExpression (max_runs=1 per task_id).
    """
    debug_section("Autonomous Execution", task_id=task_id, project_id=project_id)
    logger.info("Starting autonomous execution", task_id=task_id, project_id=project_id)
    emit_log(task_id, "info", "Starting autonomous execution", project_id=project_id)
    duplicate = _guard_existing_same_task_lane(task_id, project_id)
    if duplicate:
        return duplicate
    return execute_task_locked(task_id, project_id, dispatch=dispatch)


def _prepare_execution(
    task_id: str, project_id: str,
) -> tuple[dict[str, Any] | None, str | None, str | None, str | None]:
    """Validate task and set up the shared checkout. Returns (error, path, task_type, agent_override)."""
    task = task_store.get_task(task_id)
    if not task:
        emit_error(task_id, "Task not found", recoverable=False, project_id=project_id)
        return {"task_id": task_id, "status": "error", "message": "Task not found"}, None, None, None

    task_type = task.get("task_type")
    agent_override = task.get("agent_override")

    if not validate_pristine_codebase(task_id, project_id):
        return (
            {"task_id": task_id, "status": "failed", "error": "Pristine validation failed", "reason": "pristine_self_heal_failed"},
            None, None, None,
        )

    project_path = setup_task_checkout(task_id, project_id)
    if not project_path:
        return (
            {"task_id": task_id, "status": "failed", "error": "Task branch setup failed", "reason": "task_branch_setup_failed"},
            None, None, None,
        )

    return None, project_path, task_type, agent_override


def _has_active_task_checkpoint(task_id: str, project_id: str) -> bool:
    """Return whether the task still has active checkpoint metadata to clean up."""
    from cli.lib.checkpoint_metadata import load_snapshot_meta

    meta = load_snapshot_meta(task_id)
    return meta is not None and meta.project_id == project_id


def _prepare_completed_task_closeout(task_id: str, project_id: str) -> dict[str, Any] | None:
    """Run safety checks before early-completing a task whose subtasks already passed."""
    if not validate_pristine_codebase(task_id, project_id):
        return {
            "task_id": task_id,
            "status": "failed",
            "error": "Pristine validation failed",
            "reason": "pristine_self_heal_failed",
        }

    if not _has_active_task_checkpoint(task_id, project_id):
        emit_log(task_id, "info", "All subtasks already complete; skipping checkout setup", project_id=project_id)
        return None

    existing_checkout = get_task_checkout(task_id, project_id)
    if not existing_checkout:
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
    project_path = setup_task_checkout(task_id, project_id)
    if project_path:
        return None

    return {
        "task_id": task_id,
        "status": "failed",
        "error": "Task branch setup failed",
        "reason": "task_branch_setup_failed",
    }


def _load_subtasks(
    task_id: str,
    project_id: str,
) -> tuple[dict[str, Any] | None, list, int, int]:
    """Load subtasks. Returns (error, incomplete, total, completed)."""
    subtasks = get_subtasks_for_task(task_id, include_steps=True)
    incomplete = [s for s in subtasks if not s.get("passes")]
    total = len(subtasks)
    completed = total - len(incomplete)
    emit_progress(task_id, total_subtasks=total, completed_subtasks=completed, project_id=project_id)
    if total == 0:
        emit_error(task_id, "No subtasks to execute — planning may have failed", project_id=project_id)
        task_store.update_task_status(task_id, "failed")
        return {"task_id": task_id, "status": "failed", "error": "No subtasks to execute", "reason": "no_subtasks"}, [], 0, 0
    return None, incomplete, total, completed


def _handle_completion(
    task_id: str, project_id: str, project_path: str,
    results: list, incomplete: list, dispatch: Callable[[str, str, str], None] | None,
) -> str | None:
    """Route to appropriate completion handler based on results."""
    all_passed = all(r.get("status") == "passed" for r in results)
    any_passed = any(r.get("status") == "passed" for r in results)
    if all_passed and len(results) == len(incomplete):
        return "passed" if handle_successful_completion(task_id, project_id, project_path, results, dispatch) else "failed"
    if any_passed:
        if handle_partial_completion(task_id, project_id, project_path, results, dispatch):
            return "partial"
        handle_failed_execution(task_id, project_id, results=results)
        return "failed"
    handle_failed_execution(task_id, project_id, results=results)
    return "failed"


def execute_task_locked(
    task_id: str,
    project_id: str,
    dispatch: Callable[[str, str, str], None] | None = None,
) -> dict[str, Any]:
    """Inner execution body. Concurrency handled by Hatchet."""
    task = task_store.get_task(task_id)
    if not task:
        emit_error(task_id, "Task not found", recoverable=False, project_id=project_id)
        return {"task_id": task_id, "status": "error", "message": "Task not found"}

    error, incomplete, total, completed = _load_subtasks(task_id, project_id)
    if error:
        return error

    if not incomplete:
        completion_error = _prepare_completed_task_closeout(task_id, project_id)
        if completion_error:
            return completion_error
        return handle_early_completion(task_id, project_id, total, dispatch)

    error, project_path, task_type, agent_override = _prepare_execution(task_id, project_id)
    if error:
        return error
    assert project_path is not None

    task = task_store.get_task(task_id)
    if task and task.get("status") != "running":
        task_store.update_task_status(task_id, "running")

    results, completed = execute_subtask_loop(
        task_id, project_id, project_path, incomplete, total, completed,
        task_type, agent_override,
    )

    check_main_repo_leakage(task_id, project_id, project_path)

    _handle_completion(task_id, project_id, project_path, results, incomplete, dispatch)
    if results:
        try:
            execute_agent_feedback(
                task_id, project_path, project_id, results,
                agent_slug=agent_override or "coder",
            )
        except Exception as e:
            emit_log(
                task_id,
                "warning",
                f"Agent feedback collection failed after completion routing: {type(e).__name__}: {e}",
                source="orchestrator",
                project_id=project_id,
            )
    return {"task_id": task_id, "status": "executed", "subtask_results": results}
