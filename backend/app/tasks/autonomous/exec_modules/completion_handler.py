"""Task completion and quality gate handling."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ....logging_config import get_logger
from ....storage import tasks as task_store
from .events import emit_error, emit_log
from .git_ops import auto_commit, has_uncommitted_changes
from .quality import auto_fix_quality, run_final_quality_gate

logger = get_logger(__name__)


def handle_early_completion(
    task_id: str,
    project_id: str,
    total_subtasks: int,
    dispatch: Callable[[str, str, str], None] | None = None,
) -> dict[str, Any]:
    """Handle case where all subtasks are already complete.

    Args:
        task_id: The task ID
        project_id: The project ID
        total_subtasks: Total number of subtasks
        dispatch: Optional callback to trigger downstream workflows

    Returns:
        Result dict with status ai_reviewing
    """
    try:
        task_store.update_task(
            task_id,
            verification_result={
                "execution_clean": True,
                "subtask_count": total_subtasks,
                "total_self_fix_attempts": 0,
                "total_supervisor_attempts": 0,
            },
        )
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


def handle_successful_completion(
    task_id: str,
    project_id: str,
    project_path: str,
    results: list[dict[str, Any]],
    dispatch: Callable[[str, str, str], None] | None = None,
) -> bool:
    """Handle successful task completion with quality gate.

    Args:
        task_id: The task ID
        project_id: The project ID
        project_path: Path to project directory
        results: List of subtask execution results
        dispatch: Optional callback to trigger downstream workflows

    Returns:
        True if completed successfully, False if blocked
    """
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
                r.get("self_fix_attempts", 0) == 0 and r.get("supervisor_guided_attempts", 0) == 0
                for r in results
            )
            total_extensions = sum(r.get("extensions_granted", 0) for r in results)
            task_store.update_task(
                task_id,
                verification_result={
                    "execution_clean": execution_clean,
                    "subtask_count": len(results),
                    "total_self_fix_attempts": sum(r.get("self_fix_attempts", 0) for r in results),
                    "total_supervisor_attempts": sum(
                        r.get("supervisor_guided_attempts", 0) for r in results
                    ),
                    "total_extensions_granted": total_extensions,
                },
            )
            task_store.update_task_status(task_id, "ai_reviewing")
            emit_log(
                task_id,
                "info",
                f"All subtasks passed + quality gate passed, starting QA review (clean={execution_clean})",
                project_id=project_id,
            )
            if dispatch:
                dispatch("review", task_id, project_id)
            return True
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
            return False
    else:
        task_store.update_task_status(task_id, "blocked")
        emit_error(
            task_id,
            "Final quality gate failed after auto-fix attempt",
            project_id=project_id,
        )
        return False


def handle_failed_execution(task_id: str, project_id: str) -> None:
    """Handle case where subtasks failed.

    Args:
        task_id: The task ID
        project_id: The project ID
    """
    try:
        task_store.update_task_status(task_id, "blocked")
        emit_log(
            task_id,
            "info",
            "Execution paused - subtask verification failed",
            project_id=project_id,
        )
    except Exception as e:
        emit_log(
            task_id,
            "error",
            f"Failed to set blocked status: {type(e).__name__}: {e!s}",
            project_id=project_id,
        )
