"""3-2-1 Escalation pattern for autonomous execution.

Escalation tiers:
- Worker: 3 failures on same issue -> escalate to supervisor
- Supervisor: 2 failures -> block with recommendation
"""

from __future__ import annotations

from ...constants import QA_SUPERVISOR_STUCK_THRESHOLD, QA_WORKER_STUCK_THRESHOLD
from ...logging_config import get_logger
from ...storage import tasks as task_store
from ._escalation_helpers import (
    add_escalation_message,
    build_step_context,
    call_supervisor,
    log_guidance,
)

logger = get_logger(__name__)

WORKER_MAX_FAILURES: int = QA_WORKER_STUCK_THRESHOLD
SUPERVISOR_MAX_ATTEMPTS: int = QA_SUPERVISOR_STUCK_THRESHOLD

_STATUS_BLOCKED: str = "blocked"
_STATUS_GUIDANCE_PROVIDED: str = "guidance_provided"


def check_escalation_needed(
    failure_count: int = 0,
    supervisor_attempts: int = 0,
) -> dict[str, bool]:
    """Check if escalation is needed based on failure counts."""
    return {
        "escalate_to_supervisor": (
            failure_count >= WORKER_MAX_FAILURES and supervisor_attempts < SUPERVISOR_MAX_ATTEMPTS
        ),
        "escalate_to_human": supervisor_attempts >= SUPERVISOR_MAX_ATTEMPTS,
    }


def get_supervisor_guidance_sync(
    task_id: str,
    subtask_id: str,
    issue_description: str,
    step_outputs: list[dict[str, str | int | bool]] | None = None,
    project_id: str | None = None,
) -> str | None:
    """Get supervisor guidance synchronously for self-healing loop.

    Called when worker exhausts self-fix attempts. Returns guidance text
    to feed into next agent iteration.
    """
    logger.info("Requesting supervisor guidance (sync)", task_id=task_id, subtask_id=subtask_id)
    step_context = build_step_context(step_outputs or [])
    prompt = f"Task ID: {task_id}\nSubtask: {subtask_id}\nIssue: {issue_description}{step_context}"
    guidance = call_supervisor(prompt, project_id)
    if guidance:
        log_guidance(task_id, subtask_id, guidance)
    return guidance


def supervisor_guidance(
    task_id: str,
    subtask_id: str,
    issue_description: str,
    failure_count: int,
    project_id: str | None = None,
) -> dict[str, str | int]:
    """Get supervisor guidance for a stuck worker.

    NOTE: Kept for backward compatibility.
    Prefer get_supervisor_guidance_sync() for self-healing loop.

    Supervisor provides guidance, NOT implementation.
    After 2 attempts, escalates to human review.
    """
    logger.info(
        "Supervisor guidance requested",
        task_id=task_id,
        subtask_id=subtask_id,
        failure_count=failure_count,
    )
    if failure_count >= QA_SUPERVISOR_STUCK_THRESHOLD:
        return _block_with_recommendation(task_id, subtask_id, issue_description, failure_count, project_id=project_id)

    prompt = (
        f"Task ID: {task_id}\nSubtask: {subtask_id}\n"
        f"Issue: {issue_description}\nWorker Attempts: {failure_count}"
    )
    guidance = call_supervisor(prompt, project_id)
    if not guidance:
        return _block_with_recommendation(task_id, subtask_id, issue_description, failure_count, project_id=project_id)

    log_guidance(task_id, subtask_id, guidance)
    return {
        "task_id": task_id,
        "subtask_id": subtask_id,
        "status": _STATUS_GUIDANCE_PROVIDED,
        "guidance": guidance,
        "supervisor_attempts": failure_count + 1,
    }


def _block_with_recommendation(
    task_id: str,
    subtask_id: str,
    issue_description: str,
    attempts: int,
    project_id: str | None = None,
) -> dict[str, str | int]:
    """Block task with supervisor recommendation."""
    logger.info("Blocking task with recommendation", task_id=task_id, subtask_id=subtask_id)
    prompt = (
        f"Task ID: {task_id}\nSubtask: {subtask_id}\n"
        f"Issue: {issue_description}\nTotal Attempts: {attempts}"
    )
    recommendation = call_supervisor(prompt, project_id) or f"Issue in {subtask_id}: {issue_description}"
    task_store.update_task_status(task_id, _STATUS_BLOCKED)
    add_escalation_message(task_id, subtask_id, recommendation, attempts)
    return {
        "task_id": task_id,
        "subtask_id": subtask_id,
        "status": _STATUS_BLOCKED,
        "recommendation": recommendation,
        "total_attempts": attempts,
    }


def check_worker_stuck(
    _task_id: str,
    _subtask_id: str,
    _issue_hash: str,
    current_failures: int,
) -> tuple[bool, str]:
    """Check if worker is stuck on the same issue.

    Returns:
        (should_escalate, escalation_level) tuple.
    """
    if current_failures >= QA_WORKER_STUCK_THRESHOLD:
        return True, "supervisor"
    return False, "worker"
