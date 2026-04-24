"""Pristine codebase validation and self-healing."""

from __future__ import annotations

from ....logging_config import get_logger
from ....storage import tasks as task_store
from .events import emit_error, emit_log
from .quality import PristineCheckError, check_pristine_codebase, pristine_self_heal

logger = get_logger(__name__)


def validate_pristine_codebase(task_id: str, project_id: str) -> bool:
    """Verify codebase is pristine before automated execution.

    First tries self-healing, then falls back to blocking.

    Args:
        task_id: The task ID
        project_id: The project ID

    Returns:
        True if pristine or successfully healed, False if blocked
    """
    try:
        emit_log(task_id, "info", "Running pristine check (st check --check)...", project_id=project_id)
        check_pristine_codebase(project_id)
        emit_log(task_id, "info", "Pristine check passed", project_id=project_id)
        return True
    except PristineCheckError as e:
        emit_log(
            task_id,
            "warn",
            f"Pristine check failed, attempting self-heal: {str(e)[:100]}",
            project_id=project_id,
        )

        if pristine_self_heal(task_id, project_id):
            emit_log(task_id, "info", "Pristine self-heal succeeded", project_id=project_id)
            return True

        from ....constants import PRISTINE_SELF_HEAL_MAX_ATTEMPTS

        logger.error("pristine_self_heal_failed", task_id=task_id, error=str(e))
        task_store.update_task_status(task_id, "failed", error_message=str(e))
        emit_error(
            task_id,
            f"Pristine self-heal failed after {PRISTINE_SELF_HEAL_MAX_ATTEMPTS} attempts: {e}",
            recoverable=False,
            project_id=project_id,
        )
        return False
