"""Main task orchestration and execution flow."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ....core.debug import debug_section
from ....logging_config import get_logger
from ....storage import tasks as task_store
from ....storage.subtasks import get_subtasks_for_task
from .completion_handler import (
    handle_early_completion,
    handle_failed_execution,
    handle_partial_completion,
    handle_successful_completion,
)
from .events import emit_error, emit_log, emit_progress
from .execution_loop import execute_subtask_loop
from .pristine_validation import validate_pristine_codebase
from .steps import reset_steps_for_rerun
from .worktree import check_main_repo_leakage
from .worktree_setup import setup_worktree

logger = get_logger(__name__)


def start_execution(
    task_id: str,
    project_id: str,
    dispatch: Callable[[str, str, str], None] | None = None,
) -> dict[str, Any]:
    """Start autonomous execution of a task.

    Executes subtasks in order with fresh context per subtask.
    Uses complete() with execute_tools=True for agentic execution.

    Concurrency is handled by Hatchet ConcurrencyExpression (max_runs=1 per task_id).

    Args:
        task_id: The task ID to execute
        project_id: The project ID
        dispatch: Optional callback to trigger downstream workflows

    Returns:
        Execution result with status
    """
    debug_section("Autonomous Execution", task_id=task_id, project_id=project_id)
    logger.info("Starting autonomous execution", task_id=task_id, project_id=project_id)

    emit_log(task_id, "info", "Starting autonomous execution", project_id=project_id)

    return execute_task_locked(task_id, project_id, dispatch=dispatch)


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

    # Extract agent routing info
    task_type = task.get("task_type")
    agent_override = task.get("agent_override")

    # Resolve tier preference from project config
    from ....storage.agent_configs_autonomous import get_preferred_model_tier

    tier_preference = get_preferred_model_tier(project_id)

    # Verify codebase is pristine before automated execution
    if not validate_pristine_codebase(task_id, project_id):
        return {
            "task_id": task_id,
            "status": "blocked",
            "error": "Pristine validation failed",
            "reason": "pristine_self_heal_failed",
        }

    # Setup worktree and handle orphaned changes
    project_path = setup_worktree(task_id, project_id)
    if not project_path:
        return {
            "task_id": task_id,
            "status": "blocked",
            "error": "Worktree creation failed",
            "reason": "worktree_creation_failed",
        }

    task_store.update_task_status(task_id, "running")

    subtasks = get_subtasks_for_task(task_id, include_steps=True)
    reset_steps_for_rerun(subtasks)
    incomplete = [s for s in subtasks if not s.get("passes")]
    total = len(subtasks)
    completed = total - len(incomplete)

    emit_progress(
        task_id, total_subtasks=total, completed_subtasks=completed, project_id=project_id
    )

    # Handle case where all subtasks are already complete
    if not incomplete:
        return handle_early_completion(task_id, project_id, total, dispatch)

    # Execute incomplete subtasks
    results, completed = execute_subtask_loop(
        task_id,
        project_id,
        project_path,
        incomplete,
        total,
        completed,
        task_type,
        agent_override,
        tier_preference=tier_preference,
    )

    # Check for main repo leakage
    check_main_repo_leakage(task_id, project_id, project_path)

    # Handle completion or failure
    all_passed = all(r.get("status") == "passed" for r in results)
    any_passed = any(r.get("status") == "passed" for r in results)
    if all_passed and len(results) == len(incomplete):
        handle_successful_completion(task_id, project_id, project_path, results, dispatch)
    elif any_passed:
        # Partial success: merge passing work, create follow-up for failures
        if not handle_partial_completion(
            task_id, project_id, project_path, results, dispatch
        ):
            handle_failed_execution(task_id, project_id)
    else:
        handle_failed_execution(task_id, project_id)

    return {"task_id": task_id, "status": "executed", "subtask_results": results}
