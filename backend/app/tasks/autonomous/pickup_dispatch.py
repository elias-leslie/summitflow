"""Dispatch logic for autonomous task pipeline stages.

Handles dispatching tasks to triage, planning, or execution stages.
"""

from __future__ import annotations

from collections.abc import Callable

from app.logging_config import get_logger
from app.storage.tasks.claims import claim_task

logger = get_logger(__name__)


def dispatch_to_triage(
    task_id: str,
    project_id: str,
    dispatch: Callable[[str, str, str], None] | None,
) -> bool:
    """Dispatch task to triage stage.

    Args:
        task_id: Task ID to dispatch
        project_id: Project ID
        dispatch: Dispatch callback function

    Returns:
        True if dispatched
    """
    if dispatch:
        dispatch("triage", task_id, project_id)
    logger.info("Dispatched to triage", task_id=task_id)
    return True


def dispatch_to_planning(
    task_id: str,
    project_id: str,
    dispatch: Callable[[str, str, str], None] | None,
) -> bool:
    """Dispatch task to planning stage.

    Args:
        task_id: Task ID to dispatch
        project_id: Project ID
        dispatch: Dispatch callback function

    Returns:
        True if dispatched
    """
    if dispatch:
        dispatch("plan", task_id, project_id)
    logger.info("Dispatched to planning", task_id=task_id)
    return True


def dispatch_to_execution(
    task_id: str,
    project_id: str,
    dispatch: Callable[[str, str, str], None] | None,
    worker_id_prefix: str = "pickup",
) -> bool:
    """Dispatch task to execution stage with claim.

    Args:
        task_id: Task ID to dispatch
        project_id: Project ID
        dispatch: Dispatch callback function
        worker_id_prefix: Prefix for worker ID (pickup or dispatch)

    Returns:
        True if dispatched, False if already claimed
    """
    worker_id = f"{worker_id_prefix}-{project_id}"
    claimed = claim_task(task_id, worker_id, lock_duration_minutes=60)
    if not claimed:
        logger.info("Task already claimed, skipping", task_id=task_id)
        return False

    if dispatch:
        dispatch("execute", task_id, project_id)
    logger.info("Dispatched to execution", task_id=task_id)
    return True


def dispatch_to_stage(
    stage: str,
    task_id: str,
    project_id: str,
    dispatch: Callable[[str, str, str], None] | None,
    worker_id_prefix: str = "pickup",
) -> bool:
    """Dispatch task to appropriate pipeline stage.

    Args:
        stage: Stage name (triage, planning, execution)
        task_id: Task ID to dispatch
        project_id: Project ID
        dispatch: Dispatch callback function
        worker_id_prefix: Prefix for worker ID when claiming

    Returns:
        True if dispatched, False if skipped/failed
    """
    if stage == "triage":
        return dispatch_to_triage(task_id, project_id, dispatch)

    if stage == "planning":
        return dispatch_to_planning(task_id, project_id, dispatch)

    if stage == "execution":
        return dispatch_to_execution(task_id, project_id, dispatch, worker_id_prefix)

    logger.warning("Unknown stage, skipping", task_id=task_id, stage=stage)
    return False


def dispatch_to_review(
    task_id: str,
    project_id: str,
    dispatch: Callable[[str, str, str], None] | None,
) -> bool:
    """Dispatch task to AI review stage.

    Args:
        task_id: Task ID to dispatch
        project_id: Project ID
        dispatch: Dispatch callback function

    Returns:
        True if dispatched
    """
    if dispatch:
        dispatch("review", task_id, project_id)
    logger.info("Dispatched to AI review", task_id=task_id)
    return True
