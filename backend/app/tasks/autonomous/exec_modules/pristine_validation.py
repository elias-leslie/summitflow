"""Pristine codebase validation and baseline blocker routing."""

from __future__ import annotations

from ....logging_config import get_logger
from .baseline_blockers import ensure_quality_gate_blocker, is_baseline_quality_gate_task
from .events import emit_error, emit_log
from .quality import PristineCheckError, check_pristine_codebase

logger = get_logger(__name__)


def validate_pristine_codebase(task_id: str, project_id: str) -> bool:
    """Verify codebase is pristine before automated execution.

    Red baseline gates create/link a dedicated quality-fix blocker task.

    Args:
        task_id: The task ID
        project_id: The project ID

    Returns:
        True if pristine, False if blocked by a baseline quality task.
    """
    if is_baseline_quality_gate_task(task_id):
        emit_log(
            task_id,
            "info",
            "Skipping pristine pre-check for baseline quality gate fixer task",
            project_id=project_id,
        )
        return True

    try:
        emit_log(task_id, "info", "Running pristine check (st check --quick)...", project_id=project_id)
        check_pristine_codebase(project_id)
        emit_log(task_id, "info", "Pristine check passed", project_id=project_id)
        return True
    except PristineCheckError as e:
        blocker_task_id = ensure_quality_gate_blocker(
            task_id,
            project_id,
            error_message=str(e),
            output=e.output,
        )
        logger.warning(
            "baseline_quality_gate_blocked_task",
            task_id=task_id,
            project_id=project_id,
            blocker_task_id=blocker_task_id,
        )
        emit_log(
            task_id,
            "warn",
            f"Baseline quality gate blocks execution; created/linked blocker task {blocker_task_id}",
            project_id=project_id,
        )
        emit_error(
            task_id,
            f"Execution blocked by baseline quality gate. Work blocker task first: {blocker_task_id}",
            recoverable=True,
            project_id=project_id,
        )
        return False
