"""Main subtask execution loop."""

from __future__ import annotations

from typing import Any

from ....logging_config import get_logger
from .events import emit_log, emit_progress
from .git_ops import has_uncommitted_changes, smart_commit_result
from .interruption import ExecutionInterrupted, assert_task_runnable
from .session import WindDownState, wind_down
from .subtask_executor import MAX_ITERATIONS, execute_subtask

logger = get_logger(__name__)

def _dependency_ids(subtask: dict[str, Any]) -> list[str]:
    deps = subtask.get("depends_on")
    if not isinstance(deps, list):
        return []
    return [str(dep).strip() for dep in deps if str(dep).strip()]


def _order_subtasks_by_dependencies(
    incomplete_subtasks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return incomplete subtasks in dependency-first order."""
    subtask_by_id = {
        str(subtask.get("subtask_id") or "").strip(): subtask
        for subtask in incomplete_subtasks
        if str(subtask.get("subtask_id") or "").strip()
    }
    ordered: list[dict[str, Any]] = []
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(subtask: dict[str, Any]) -> None:
        subtask_id = str(subtask.get("subtask_id") or "").strip()
        if not subtask_id or subtask_id in visited:
            return
        if subtask_id in visiting:
            ordered.append(subtask)
            visited.add(subtask_id)
            return
        visiting.add(subtask_id)
        for dependency_id in _dependency_ids(subtask):
            dependency = subtask_by_id.get(dependency_id)
            if dependency is not None:
                visit(dependency)
        visiting.discard(subtask_id)
        if subtask_id not in visited:
            ordered.append(subtask)
            visited.add(subtask_id)

    for subtask in incomplete_subtasks:
        visit(subtask)

    return ordered


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
        commit_result = smart_commit_result(
            project_path,
            f"[FAILED] {commit_msg}",
            task_id=task_id,
            push=True,
            skip_checks=True,
        )
        if commit_result.get("success"):
            emit_log(task_id, "info", f"Preserved failing changes for subtask {subtask_short_id}", project_id=project_id)
            return
    else:
        commit_result = smart_commit_result(project_path, commit_msg, task_id=task_id, push=True)
        if commit_result.get("success"):
            emit_log(task_id, "info", f"Published changes for subtask {subtask_short_id}", project_id=project_id)
            return

    detail = str(commit_result.get("detail") or "unknown preservation failure")
    emit_log(
        task_id,
        "warn",
        f"Failed to preserve changes for subtask {subtask_short_id}: {detail}",
        project_id=project_id,
    )


def _handle_subtask_failure(
    task_id: str,
    project_id: str,
    result: dict[str, Any],
) -> bool:
    """Log subtask failure and let normal task completion fail."""
    self_fix_attempts = result.get("self_fix_attempts", 0)
    supervisor_guided_attempts = result.get("supervisor_guided_attempts", 0)
    total_attempts = 1 + self_fix_attempts + supervisor_guided_attempts

    step_results = result.get("step_results", [])
    failed_steps = [s for s in step_results if not s.get("passed")]
    failure_detail = ""
    if failed_steps:
        reasons = [str(s.get("reason") or s.get("error") or "unknown")[:80] for s in failed_steps[:2]]
        failure_detail = f": {'; '.join(reasons)}"
    emit_log(
        task_id, "warn",
        f"Subtask {result.get('subtask_id')} failed after {total_attempts} attempts{failure_detail}",
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
) -> tuple[list[dict[str, Any]], int, WindDownState | None]:
    """Execute incomplete subtasks in order; returns (results, final completed count, wind_down_state)."""
    results: list[dict[str, Any]] = []
    issue_counts: dict[str, int] = {}
    completed = completed_count
    ordered_subtasks = _order_subtasks_by_dependencies(incomplete_subtasks)

    for iteration, subtask in enumerate(ordered_subtasks, 1):
        if iteration > MAX_ITERATIONS:
            emit_log(task_id, "warn", f"Max iterations ({MAX_ITERATIONS}) reached", project_id=project_id)
            return results, completed, wind_down(task_id, results, ordered_subtasks, "max_iterations")

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
            return results, completed, wind_down(task_id, results, ordered_subtasks, exc.reason)
        results.append(result)
        completed += 1
        status = "passed" if result.get("status") == "passed" else "failed"
        emit_progress(task_id, subtask_id=result.get("subtask_id"), status=status, total_subtasks=total_subtasks, completed_subtasks=completed, project_id=project_id)
        _commit_subtask_changes(project_path, task_id, project_id, subtask, status)

        if result.get("status") == "failed" and not _handle_subtask_failure(task_id, project_id, result):
            break

    return results, completed, None
