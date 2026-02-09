"""Main task orchestration and execution flow."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ....core.debug import debug_section
from ....logging_config import get_logger
from ....services.worktree import create_task_worktree
from ....storage import tasks as task_store
from ....storage.subtasks import get_subtasks_for_task
from .agent_routing import supervisor_circuit_breaker_triage
from .events import emit_error, emit_log, emit_progress
from .git_ops import auto_commit, has_uncommitted_changes, smart_commit
from .quality import (
    PristineCheckError,
    auto_fix_quality,
    check_pristine_codebase,
    pristine_self_heal,
    run_final_quality_gate,
)
from .session import wind_down
from .steps import reset_steps_for_rerun
from .subtask_executor import MAX_ITERATIONS, execute_subtask
from .worktree import check_main_repo_leakage, get_project_path

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

    # Verify codebase is pristine before automated execution
    # First try self-healing, then fall back to blocking
    try:
        emit_log(task_id, "info", "Running pristine check (dt --check)...", project_id=project_id)
        check_pristine_codebase(project_id)
        emit_log(task_id, "info", "Pristine check passed", project_id=project_id)
    except PristineCheckError as e:
        emit_log(
            task_id,
            "warn",
            f"Pristine check failed, attempting self-heal: {str(e)[:100]}",
            project_id=project_id,
        )

        if pristine_self_heal(task_id, project_id):
            emit_log(task_id, "info", "Pristine self-heal succeeded", project_id=project_id)
        else:
            from ....constants import PRISTINE_SELF_HEAL_MAX_ATTEMPTS

            logger.error("pristine_self_heal_failed", task_id=task_id, error=str(e))
            task_store.update_task_status(task_id, "blocked", error_message=str(e))
            emit_error(
                task_id,
                f"Pristine self-heal failed after {PRISTINE_SELF_HEAL_MAX_ATTEMPTS} attempts: {e}",
                recoverable=False,
                project_id=project_id,
            )
            return {
                "task_id": task_id,
                "status": "blocked",
                "error": str(e),
                "reason": "pristine_self_heal_failed",
            }

    worktree = create_task_worktree(task_id, project_id)
    if worktree:
        emit_log(task_id, "info", f"Worktree ready: {worktree.path}", project_id=project_id)
    else:
        emit_error(
            task_id,
            "Worktree creation failed — refusing to execute on main branch",
            recoverable=False,
            project_id=project_id,
        )
        task_store.update_task_status(task_id, "blocked")
        return {
            "task_id": task_id,
            "status": "blocked",
            "error": "Worktree creation failed",
            "reason": "worktree_creation_failed",
        }

    project_path = get_project_path(project_id, task_id)
    if has_uncommitted_changes(project_path):
        emit_log(
            task_id,
            "warn",
            "Found uncommitted changes from previous session, auto-committing",
            project_id=project_id,
        )
        if auto_commit(project_path, "WIP: uncommitted changes from previous session"):
            emit_log(task_id, "info", "Orphaned changes committed", project_id=project_id)

    task_store.update_task_status(task_id, "running")

    subtasks = get_subtasks_for_task(task_id, include_steps=True)
    reset_steps_for_rerun(subtasks)
    incomplete = [s for s in subtasks if not s.get("passes")]
    total = len(subtasks)
    completed = total - len(incomplete)

    emit_progress(
        task_id, total_subtasks=total, completed_subtasks=completed, project_id=project_id
    )

    if not incomplete:
        try:
            task_store.update_task(task_id, verification_result={
                "execution_clean": True,
                "subtask_count": total,
                "total_self_fix_attempts": 0,
                "total_supervisor_attempts": 0,
            })
            task_store.update_task_status(task_id, "ai_reviewing")
            emit_log(
                task_id,
                "info",
                "All subtasks already complete, starting QA review",
                project_id=project_id,
            )
            if dispatch:
                dispatch("review", task_id, project_id)
        except Exception as e:
            emit_log(
                task_id,
                "error",
                f"Failed to transition to ai_reviewing: {e}",
                project_id=project_id,
            )
            task_store.update_task_status(task_id, "blocked")
        return {
            "task_id": task_id,
            "status": "ai_reviewing",
            "message": "Triggered QA review for complete subtasks",
        }

    # Track results across loop
    results: list[dict[str, Any]] = []
    issue_counts: dict[str, int] = {}

    for iteration, subtask in enumerate(incomplete, 1):
        if iteration > MAX_ITERATIONS:
            emit_log(
                task_id, "warn", f"Max iterations ({MAX_ITERATIONS}) reached", project_id=project_id
            )
            wind_down(task_id, results, incomplete, "max_iterations")
            break

        result = execute_subtask(
            task_id, subtask, project_id, issue_counts, task_type, agent_override
        )
        results.append(result)
        completed += 1
        status = "passed" if result.get("status") == "passed" else "failed"
        emit_progress(
            task_id,
            subtask_id=result.get("subtask_id"),
            status=status,
            total_subtasks=total,
            completed_subtasks=completed,
            project_id=project_id,
        )

        subtask_short_id = subtask.get("subtask_id", "")
        subtask_desc = subtask.get("description", "")[:50]
        if has_uncommitted_changes(project_path):
            commit_msg = f"Subtask {subtask_short_id}: {subtask_desc}"
            if status == "failed":
                commit_msg = f"[FAILED] {commit_msg}"
                auto_commit(project_path, commit_msg)
            elif smart_commit(project_path, commit_msg, task_id):
                emit_log(
                    task_id,
                    "info",
                    f"Committed changes for subtask {subtask_short_id}",
                    project_id=project_id,
                )

        if result.get("status") == "failed":
            self_fix_attempts = result.get("self_fix_attempts", 0)
            supervisor_guided_attempts = result.get("supervisor_guided_attempts", 0)
            total_attempts = 1 + self_fix_attempts + supervisor_guided_attempts

            # Circuit breaker: same issue repeating across subtasks
            issue_id = result.get("issue_id")
            if issue_id and issue_counts.get(issue_id, 0) >= 2:
                should_continue = supervisor_circuit_breaker_triage(
                    task_id, issue_id, issue_counts[issue_id], project_id,
                )
                if not should_continue:
                    emit_log(
                        task_id,
                        "error",
                        f"Circuit breaker: supervisor says stop after {issue_id} "
                        f"repeated {issue_counts[issue_id]} times",
                        source="supervisor",
                        project_id=project_id,
                    )
                    task_store.update_task_status(task_id, "blocked")
                    return {"task_id": task_id, "status": "blocked", "subtask_results": results}
                emit_log(
                    task_id,
                    "warn",
                    f"Circuit breaker: supervisor says continue despite {issue_id} "
                    f"repeated {issue_counts[issue_id]} times",
                    source="supervisor",
                    project_id=project_id,
                )

            # Log failure and continue to next subtask
            emit_log(
                task_id,
                "warn",
                f"Subtask {result.get('subtask_id')} failed after {total_attempts} attempts, continuing",
                project_id=project_id,
            )

    check_main_repo_leakage(task_id, project_id, project_path)

    all_passed = all(r.get("status") == "passed" for r in results)
    if all_passed and len(results) == len(incomplete):
        final_gate_passed = run_final_quality_gate(task_id, project_path, project_id)
        if not final_gate_passed:
            emit_log(
                task_id,
                "warn",
                "Final quality gate failed, attempting auto-fix",
                source="quality",
                project_id=project_id,
            )
            auto_fix_quality(project_path)
            if has_uncommitted_changes(project_path):
                auto_commit(project_path, f"[auto-fix] Quality gate fixes for {task_id}")
            final_gate_passed = run_final_quality_gate(task_id, project_path, project_id)

        if final_gate_passed:
            try:
                execution_clean = all(
                    r.get("self_fix_attempts", 0) == 0
                    and r.get("supervisor_guided_attempts", 0) == 0
                    for r in results
                )
                total_extensions = sum(
                    r.get("extensions_granted", 0) for r in results
                )
                task_store.update_task(task_id, verification_result={
                    "execution_clean": execution_clean,
                    "subtask_count": len(results),
                    "total_self_fix_attempts": sum(
                        r.get("self_fix_attempts", 0) for r in results
                    ),
                    "total_supervisor_attempts": sum(
                        r.get("supervisor_guided_attempts", 0) for r in results
                    ),
                    "total_extensions_granted": total_extensions,
                })
                task_store.update_task_status(task_id, "ai_reviewing")
                emit_log(
                    task_id,
                    "info",
                    f"All subtasks passed + quality gate passed, starting QA review (clean={execution_clean})",
                    project_id=project_id,
                )
                if dispatch:
                    dispatch("review", task_id, project_id)
            except Exception as e:
                emit_log(
                    task_id,
                    "error",
                    f"Failed to transition to ai_reviewing: {type(e).__name__}: {e!s}\n"
                    f"Task ID: {task_id}\n"
                    f"Project ID: {project_id}\n"
                    f"Results: {results}",
                    project_id=project_id,
                )
                task_store.update_task_status(task_id, "blocked")
                emit_log(
                    task_id,
                    "error",
                    "Task set to blocked due to status transition failure",
                    project_id=project_id,
                )
        else:
            task_store.update_task_status(task_id, "blocked")
            emit_error(
                task_id,
                "Final quality gate failed after auto-fix attempt",
                project_id=project_id,
            )
    else:
        # Some subtasks failed - mark as blocked (not stuck in "running")
        try:
            task_store.update_task_status(task_id, "blocked")
            emit_log(
                task_id,
                "info",
                "Execution paused - subtask verification failed",
                project_id=project_id,
            )
        except Exception as e:
            # Log the failure but task is likely already in a bad state
            emit_log(
                task_id,
                "error",
                f"Failed to set blocked status: {type(e).__name__}: {e!s}",
                project_id=project_id,
            )

    return {"task_id": task_id, "status": "executed", "subtask_results": results}
