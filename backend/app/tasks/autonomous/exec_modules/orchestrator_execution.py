"""Execution body helpers for autonomous orchestrator."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def load_subtasks(
    task_id: str,
    project_id: str,
    *,
    get_subtasks_for_task: Callable[..., list],
    emit_progress: Callable[..., None],
    emit_error: Callable[..., None],
    task_store: Any,
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


def handle_completion(
    task_id: str,
    project_id: str,
    project_path: str,
    results: list,
    incomplete: list,
    dispatch: Callable[[str, str, str], None] | None,
    wind_down_state: Any,
    *,
    handle_successful_completion: Callable[..., bool],
    handle_partial_completion: Callable[..., bool],
    handle_failed_execution: Callable[..., Any],
) -> str | None:
    """Route to appropriate completion handler based on subtask results."""
    if wind_down_state and wind_down_state.paused:
        return "paused"

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


def collect_agent_feedback(
    task_id: str,
    project_path: str,
    project_id: str,
    results: list,
    *,
    agent_slug: str,
    execute_agent_feedback: Callable[..., Any],
    emit_log: Callable[..., None],
) -> None:
    if not results:
        return
    try:
        execute_agent_feedback(task_id, project_path, project_id, results, agent_slug=agent_slug)
    except Exception as exc:
        emit_log(
            task_id,
            "warning",
            f"Agent feedback collection failed after completion routing: {type(exc).__name__}: {exc}",
            source="orchestrator",
            project_id=project_id,
        )


def run_incomplete_subtasks(
    task_id: str,
    project_id: str,
    incomplete: list,
    total: int,
    completed: int,
    *,
    prepare_execution: Callable[..., tuple[dict[str, Any] | None, str | None, str | None, str | None]],
    task_store: Any,
    execute_subtask_loop: Callable[..., tuple[list, int, Any]],
) -> tuple[str, list, Any, str | None]:
    error, project_path, task_type, agent_override = prepare_execution(task_id, project_id)
    if error:
        _mark_setup_failed(task_id, task_store=task_store, error=error)
        return "", [error], None, None
    assert project_path is not None
    _mark_running(task_id, task_store=task_store)
    results, _, wind_down_state = execute_subtask_loop(
        task_id, project_id, project_path, incomplete, total, completed,
        task_type, agent_override,
    )
    return project_path, results, wind_down_state, agent_override


def execute_task_locked_impl(
    task_id: str,
    project_id: str,
    dispatch: Callable[[str, str, str], None] | None,
    *,
    deps: dict[str, Any],
) -> dict[str, Any]:
    task_store = deps["task_store"]
    task = task_store.get_task(task_id)
    if not task:
        deps["emit_error"](task_id, "Task not found", recoverable=False, project_id=project_id)
        return {"task_id": task_id, "status": "error", "message": "Task not found"}

    error, incomplete, total, completed = deps["load_subtasks"](task_id, project_id)
    if error:
        return error
    if not incomplete:
        completion_error = deps["prepare_completed_task_closeout"](task_id, project_id)
        if completion_error:
            _mark_setup_failed(task_id, task_store=task_store, error=completion_error)
            return completion_error
        return deps["handle_early_completion"](task_id, project_id, total, dispatch)

    project_path, results, wind_down_state, agent_override = run_incomplete_subtasks(
        task_id,
        project_id,
        incomplete,
        total,
        completed,
        prepare_execution=deps["prepare_execution"],
        task_store=task_store,
        execute_subtask_loop=deps["execute_subtask_loop"],
    )
    if not project_path:
        return results[0]
    return _finish_execution(task_id, project_id, project_path, results, incomplete, dispatch, wind_down_state, agent_override, deps)


def _finish_execution(
    task_id: str,
    project_id: str,
    project_path: str,
    results: list,
    incomplete: list,
    dispatch: Callable[[str, str, str], None] | None,
    wind_down_state: Any,
    agent_override: str | None,
    deps: dict[str, Any],
) -> dict[str, Any]:
    deps["check_main_repo_leakage"](task_id, project_id, project_path)
    deps["handle_completion"](task_id, project_id, project_path, results, incomplete, dispatch, wind_down_state)
    collect_agent_feedback(
        task_id,
        project_path,
        project_id,
        results,
        agent_slug=agent_override or "coder",
        execute_agent_feedback=deps["execute_agent_feedback"],
        emit_log=deps["emit_log"],
    )
    return {"task_id": task_id, "status": "executed", "subtask_results": results}


def _mark_running(task_id: str, *, task_store: Any) -> None:
    task = task_store.get_task(task_id)
    if task and task.get("status") != "running":
        task_store.update_task_status(task_id, "running")


def _mark_setup_failed(task_id: str, *, task_store: Any, error: dict[str, Any]) -> None:
    message = str(
        error.get("error")
        or error.get("message")
        or error.get("reason")
        or "Execution setup failed"
    )
    try:
        task_store.update_task_status(task_id, "failed", error_message=message)
    except ValueError:
        task_store.update_task_status(
            task_id,
            "failed",
            error_message=message,
            validate_transition=False,
        )
