"""Success and failure handlers for task execution.

Separated from loop.py to reduce file size.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ...logging_config import get_logger
from ...storage import tasks as task_store
from ...storage.agent_sessions import update_session
from ..git_service import revert_to
from .subtasks import mark_subtask_complete
from .types import ExecutionResult
from .verification import check_step_completion

logger = get_logger(__name__)


def handle_success(
    project_id: str,
    repo_path: Path,
    session_id: str,
    task_id: str,
    task: dict[str, Any],
    current_task: dict[str, Any],
    build_state: dict[str, Any],
    completed: set[str],
    iteration: int,
    model_name: str,
    models_tried: list[str],
    was_consulted: bool,
    was_handoff: bool,
    execution_start: datetime,
    test_result: dict[str, Any],
    update_phase_callback: Callable[[str, str, dict[str, Any]], None],
) -> ExecutionResult:
    """Handle successful task completion."""
    task_id_to_add = current_task.get("id") or ""
    completed.add(task_id_to_add)
    build_state["completed_tasks"] = list(completed)
    update_session(project_id, session_id, build_state=build_state)

    if build_state.get("using_subtasks_table"):
        mark_subtask_complete(current_task, str(repo_path), project_id=project_id)

    update_phase_callback(task_id, "verify", build_state)
    step_check = check_step_completion(project_id, task)

    execution_time = (datetime.now(UTC) - execution_start).total_seconds()
    task_store.update_task(
        task_id,
        review_result={
            "iterations": iteration,
            "model_used": model_name,
            "models_tried": models_tried,
            "consulted": was_consulted,
            "handoff": was_handoff,
            "reason": "success",
            "execution_time_seconds": round(execution_time, 2),
            "steps_verified": step_check["verified_count"],
            "steps_total": step_check["total"],
            "unverified_steps": step_check["unverified"],
        },
    )

    if step_check["all_verified"]:
        update_phase_callback(task_id, "complete", build_state)
        task_store.update_task_status(task_id, "completed")
        logger.info("task_completed", task_id=task_id)
    else:
        logger.warning(
            "steps_not_verified",
            task_id=task_id,
            unverified=step_check["unverified"],
        )

    return ExecutionResult(
        success=True,
        iterations=iteration,
        model_used=model_name,
        models_tried=models_tried,
        test_output=test_result.get("output"),
    )


def handle_exhaustion(
    repo_path: Path,
    task_id: str,
    build_state: dict[str, Any],
    max_iterations: int,
    models_tried: list[str],
    was_consulted: bool,
    was_handoff: bool,
    execution_start: datetime,
    iteration_context: dict[str, Any] | None,
) -> ExecutionResult:
    """Handle iteration exhaustion."""
    pre_merge_sha = build_state.get("pre_merge_sha")
    if pre_merge_sha:
        try:
            revert_to(repo_path, pre_merge_sha)
            logger.info("reverted_after_exhaustion", sha=pre_merge_sha[:8])
        except Exception as e:
            logger.error("revert_failed", error=str(e))

    execution_time = (datetime.now(UTC) - execution_start).total_seconds()
    task_store.update_task(
        task_id,
        review_result={
            "iterations": max_iterations,
            "model_used": models_tried[-1] if models_tried else "none",
            "models_tried": models_tried,
            "consulted": was_consulted,
            "handoff": was_handoff,
            "reason": "exhausted",
            "execution_time_seconds": round(execution_time, 2),
            "last_error": (
                iteration_context.get("test_failures", "")[:500] if iteration_context else None
            ),
        },
    )

    return ExecutionResult(
        success=False,
        iterations=max_iterations,
        model_used=models_tried[-1] if models_tried else "none",
        models_tried=models_tried,
        reason="exhausted",
        error=f"Failed after {max_iterations} iterations",
        test_output=(iteration_context.get("test_failures") if iteration_context else None),
    )
