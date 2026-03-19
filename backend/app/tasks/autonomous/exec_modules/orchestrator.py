"""Main task orchestration and execution flow."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ....core.debug import debug_section
from ....logging_config import get_logger
from ....services.task_lane_preflight import check_task_lane_conflicts
from ....storage import tasks as task_store
from ....storage.subtasks import get_subtasks_for_task
from .agent_execution import execute_agent_feedback
from .completion_handler import (
    handle_early_completion,
    handle_failed_execution,
    handle_partial_completion,
    handle_successful_completion,
)
from .events import emit_error, emit_log, emit_progress
from .execution_loop import execute_subtask_loop
from .pristine_validation import validate_pristine_codebase
from .worktree import check_main_repo_leakage
from .worktree_setup import setup_worktree

logger = get_logger(__name__)


def _guard_existing_same_task_lane(task_id: str, project_id: str) -> dict[str, Any] | None:
    """Avoid replaying the same task when an active live lane already exists."""
    lane_check = check_task_lane_conflicts(task_id, project_id)
    if lane_check.overlap_kind != "same_task" or lane_check.disposition != "block":
        return None

    owner = lane_check.owner_session_id or "unknown"
    emit_log(
        task_id,
        "info",
        f"Execution skipped: active task lane already owned by session {owner}",
        project_id=project_id,
    )
    logger.info(
        "Skipping duplicate autonomous execution for active task lane",
        task_id=task_id,
        project_id=project_id,
        owner_session_id=lane_check.owner_session_id,
        owner_location=lane_check.owner_location,
    )
    return {
        "task_id": task_id,
        "status": "already_running",
        "message": "Active task lane already exists",
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
    """Validate task and set up worktree. Returns (error, path, task_type, agent_override)."""
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

    project_path = setup_worktree(task_id, project_id)
    if not project_path:
        return (
            {"task_id": task_id, "status": "failed", "error": "Worktree creation failed", "reason": "worktree_creation_failed"},
            None, None, None,
        )

    return None, project_path, task_type, agent_override


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
    error, project_path, task_type, agent_override = _prepare_execution(task_id, project_id)
    if error:
        return error

    task = task_store.get_task(task_id)
    if task and task.get("status") != "running":
        task_store.update_task_status(task_id, "running")

    error, incomplete, total, completed = _load_subtasks(task_id, project_id)
    if error:
        return error

    if not incomplete:
        return handle_early_completion(task_id, project_id, total, dispatch)

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
