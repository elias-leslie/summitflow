"""Main subtask execution loop."""

from __future__ import annotations

import time
from typing import Any

from ....logging_config import get_logger
from ....storage import tasks as task_store
from ..pickup_guards import check_system_health
from .agent_routing import supervisor_circuit_breaker_triage
from .events import emit_log, emit_progress
from .git_ops import has_uncommitted_changes, smart_commit
from .interruption import ExecutionInterrupted, assert_task_runnable
from .session import wind_down
from .subtask_executor import MAX_ITERATIONS, execute_subtask

logger = get_logger(__name__)

# Health check backoff configuration
_HEALTH_CHECK_DELAYS = [30, 60, 120]  # seconds


def _check_health_or_wait(
    task_id: str,
    project_id: str,
    max_retries: int = 3,
) -> bool:
    """Check system health with exponential backoff; returns True if healthy."""
    health_error = check_system_health(project_id)
    if health_error is None:
        return True

    for retry in range(max_retries):
        delay = _HEALTH_CHECK_DELAYS[min(retry, len(_HEALTH_CHECK_DELAYS) - 1)]
        failing = health_error.get("failing_services", [])
        emit_log(
            task_id,
            "warn",
            f"System unhealthy ({', '.join(failing)}), waiting {delay}s before retry {retry + 1}/{max_retries}",
            source="health",
            project_id=project_id,
        )
        time.sleep(delay)
        health_error = check_system_health(project_id)
        if health_error is None:
            emit_log(task_id, "info", "System health recovered, resuming execution", source="health", project_id=project_id)
            return True

    return False


def _commit_subtask_changes(
    project_path: str,
    task_id: str,
    project_id: str,
    subtask: dict[str, Any],
    status: str,
) -> None:
    """Preserve any uncommitted changes after a subtask completes."""
    if not has_uncommitted_changes(project_path):
        return
    subtask_short_id = subtask.get("subtask_id", "")
    subtask_desc = subtask.get("description", "")[:50]
    commit_msg = f"Subtask {subtask_short_id}: {subtask_desc}"
    if status == "failed":
        if smart_commit(
            project_path,
            f"[FAILED] {commit_msg}",
            task_id=task_id,
            push=True,
            skip_checks=True,
        ):
            emit_log(task_id, "info", f"Preserved failing changes for subtask {subtask_short_id}", project_id=project_id)
            return
    elif smart_commit(project_path, commit_msg, task_id=task_id, push=True):
        emit_log(task_id, "info", f"Published changes for subtask {subtask_short_id}", project_id=project_id)
        return

    emit_log(task_id, "warn", f"Failed to preserve changes for subtask {subtask_short_id}", project_id=project_id)


def _handle_subtask_failure(
    task_id: str,
    project_id: str,
    result: dict[str, Any],
    issue_counts: dict[str, int],
    results: list[dict[str, Any]],
) -> bool:
    """Handle subtask failure with circuit breaker logic; returns True to continue, False to stop."""
    self_fix_attempts = result.get("self_fix_attempts", 0)
    supervisor_guided_attempts = result.get("supervisor_guided_attempts", 0)
    total_attempts = 1 + self_fix_attempts + supervisor_guided_attempts

    issue_id = result.get("issue_id")
    if issue_id and issue_counts.get(issue_id, 0) >= 3:
        should_continue = supervisor_circuit_breaker_triage(task_id, issue_id, issue_counts[issue_id], project_id)
        if not should_continue:
            emit_log(
                task_id, "error",
                f"Circuit breaker: supervisor says stop after {issue_id} repeated {issue_counts[issue_id]} times",
                source="supervisor", project_id=project_id,
            )
            task_store.update_task_status(task_id, "blocked")
            return False
        emit_log(
            task_id, "warn",
            f"Circuit breaker: supervisor says continue despite {issue_id} repeated {issue_counts[issue_id]} times",
            source="supervisor", project_id=project_id,
        )

    emit_log(
        task_id, "warn",
        f"Subtask {result.get('subtask_id')} failed after {total_attempts} attempts, continuing",
        project_id=project_id,
    )
    return True


def execute_subtask_loop(
    task_id: str,
    project_id: str,
    project_path: str,
    incomplete_subtasks: list[dict[str, Any]],
    total_subtasks: int,
    completed_count: int,
    task_type: str | None,
    agent_override: str | None,
) -> tuple[list[dict[str, Any]], int]:
    """Execute incomplete subtasks in order; returns (results, final completed count)."""
    results: list[dict[str, Any]] = []
    issue_counts: dict[str, int] = {}
    completed = completed_count

    for iteration, subtask in enumerate(incomplete_subtasks, 1):
        if iteration > MAX_ITERATIONS:
            emit_log(task_id, "warn", f"Max iterations ({MAX_ITERATIONS}) reached", project_id=project_id)
            wind_down(task_id, results, incomplete_subtasks, "max_iterations")
            break

        if not _check_health_or_wait(task_id, project_id):
            emit_log(task_id, "error", "System unhealthy after retries, winding down", source="health", project_id=project_id)
            wind_down(task_id, results, incomplete_subtasks, "system_unhealthy")
            break

        try:
            assert_task_runnable(
                task_id,
                project_id,
                f"before_subtask_{subtask.get('subtask_id', iteration)}",
            )
            result = execute_subtask(
                task_id,
                subtask,
                project_id,
                issue_counts,
                task_type,
                agent_override,
            )
        except ExecutionInterrupted as exc:
            wind_down(task_id, results, incomplete_subtasks, exc.reason)
            break
        results.append(result)
        completed += 1
        status = "passed" if result.get("status") == "passed" else "failed"
        emit_progress(task_id, subtask_id=result.get("subtask_id"), status=status, total_subtasks=total_subtasks, completed_subtasks=completed, project_id=project_id)
        _commit_subtask_changes(project_path, task_id, project_id, subtask, status)

        if result.get("status") == "failed" and not _handle_subtask_failure(task_id, project_id, result, issue_counts, results):
            break

    return results, completed
