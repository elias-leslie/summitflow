"""3-2-1 Escalation pattern for autonomous execution.

Escalation tiers:
- Worker: 3 failures on same issue -> escalate to supervisor
- Supervisor: 2 failures -> block with recommendation
"""

from __future__ import annotations

from typing import Any

from ...constants import (
    QA_SUPERVISOR_STUCK_THRESHOLD,
    QA_WORKER_STUCK_THRESHOLD,
)
from ...logging_config import get_logger
from ...services.agent_hub_client import get_sync_client
from ...storage import log_task_event
from ...storage import tasks as task_store

logger = get_logger(__name__)

WORKER_MAX_FAILURES: int = QA_WORKER_STUCK_THRESHOLD
SUPERVISOR_MAX_ATTEMPTS: int = QA_SUPERVISOR_STUCK_THRESHOLD


def check_escalation_needed(
    failure_count: int = 0,
    supervisor_attempts: int = 0,
) -> dict[str, bool]:
    """Check if escalation is needed based on failure counts.

    Args:
        failure_count: Number of worker failures on same issue
        supervisor_attempts: Number of supervisor guidance attempts

    Returns:
        Dict with escalation flags
    """
    return {
        "escalate_to_supervisor": failure_count >= WORKER_MAX_FAILURES
        and supervisor_attempts < SUPERVISOR_MAX_ATTEMPTS,
        "escalate_to_human": supervisor_attempts >= SUPERVISOR_MAX_ATTEMPTS,
    }


def get_supervisor_guidance_sync(
    task_id: str,
    subtask_id: str,
    issue_description: str,
    step_outputs: list[dict[str, Any]] | None = None,
    project_id: str | None = None,
) -> str | None:
    """Get supervisor guidance synchronously for self-healing loop.

    Called when worker exhausts self-fix attempts. Returns guidance text
    to feed into next agent iteration.

    Args:
        task_id: The task ID
        subtask_id: The subtask that's stuck
        issue_description: Description of the failure
        step_outputs: Optional list of failed step verification outputs

    Returns:
        Guidance text or None if supervisor call fails
    """
    logger.info(
        "Requesting supervisor guidance (sync)",
        task_id=task_id,
        subtask_id=subtask_id,
    )

    step_context = ""
    if step_outputs:
        step_details = []
        for step in step_outputs:
            if not step.get("passed"):
                step_details.append(
                    f"- Step {step.get('step_number')}: {step.get('reason', 'failed')}\n"
                    f"  Output: {step.get('output', '')[:300]}"
                )
        if step_details:
            step_context = "\n\nFailed step details:\n" + "\n".join(step_details)

    prompt = f"""Task ID: {task_id}
Subtask: {subtask_id}
Issue: {issue_description}{step_context}"""

    try:
        client = get_sync_client()
        response = client.complete(
            messages=[{"role": "user", "content": prompt}],
            agent_slug="supervisor",
            project_id=project_id or "summitflow",
        )

        guidance: str = response.content
        log_task_event(
            task_id,
            f"Supervisor guidance for {subtask_id}:\n{guidance[:500]}",
        )

        return guidance

    except Exception as e:
        logger.warning("Supervisor guidance failed", error=str(e))
        return None


def supervisor_guidance(
    task_id: str,
    subtask_id: str,
    issue_description: str,
    failure_count: int,
    project_id: str | None = None,
) -> dict[str, Any]:
    """Get supervisor guidance for a stuck worker (async Celery task).

    NOTE: This async version is kept for backward compatibility.
    Prefer get_supervisor_guidance_sync() for self-healing loop.

    Supervisor provides guidance, NOT implementation.
    After 2 attempts, escalates to human review.

    Args:
        task_id: The task ID
        subtask_id: The subtask that's stuck
        issue_description: Description of the failure
        failure_count: Number of supervisor attempts so far

    Returns:
        Guidance result or escalation info
    """
    logger.info(
        "Supervisor guidance requested",
        task_id=task_id,
        subtask_id=subtask_id,
        failure_count=failure_count,
    )

    if failure_count >= QA_SUPERVISOR_STUCK_THRESHOLD:
        return _block_with_recommendation(
            task_id, subtask_id, issue_description, failure_count, project_id=project_id,
        )

    prompt = f"""Task ID: {task_id}
Subtask: {subtask_id}
Issue: {issue_description}
Worker Attempts: {failure_count}"""

    try:
        client = get_sync_client()
        response = client.complete(
            messages=[{"role": "user", "content": prompt}],
            agent_slug="supervisor",
            project_id=project_id or "summitflow",
        )

        guidance = response.content
        log_task_event(
            task_id,
            f"Supervisor guidance for {subtask_id}:\n{guidance[:500]}",
        )

        return {
            "task_id": task_id,
            "subtask_id": subtask_id,
            "status": "guidance_provided",
            "guidance": guidance,
            "supervisor_attempts": failure_count + 1,
        }

    except Exception as e:
        logger.warning("Supervisor guidance failed", error=str(e))
        return _block_with_recommendation(
            task_id, subtask_id, issue_description, failure_count, project_id=project_id,
        )


def _block_with_recommendation(
    task_id: str,
    subtask_id: str,
    issue_description: str,
    attempts: int,
    project_id: str | None = None,
) -> dict[str, Any]:
    """Block task with supervisor recommendation."""
    logger.info("Blocking task with recommendation", task_id=task_id, subtask_id=subtask_id)

    prompt = f"""Task ID: {task_id}
Subtask: {subtask_id}
Issue: {issue_description}
Total Attempts: {attempts}"""

    recommendation = f"Issue in {subtask_id}: {issue_description}"

    try:
        client = get_sync_client()
        response = client.complete(
            messages=[{"role": "user", "content": prompt}],
            agent_slug="supervisor",
            project_id=project_id or "summitflow",
        )
        recommendation = response.content
    except Exception as e:
        logger.warning("Failed to generate recommendation", error=str(e))

    task_store.update_task_status(task_id, "blocked")
    _add_escalation_message(task_id, subtask_id, recommendation, attempts)

    return {
        "task_id": task_id,
        "subtask_id": subtask_id,
        "status": "blocked",
        "recommendation": recommendation,
        "total_attempts": attempts,
    }


def _add_escalation_message(
    task_id: str,
    subtask_id: str,
    recommendation: str,
    attempts: int,
) -> None:
    """Add escalation message to task chat/progress log."""
    message = f"""ESCALATION REQUIRED

Subtask: {subtask_id}
Total Attempts: {attempts}

{recommendation}

Please review and approve a direction to proceed."""

    log_task_event(task_id, message)
    logger.info("Escalation message added", task_id=task_id)


def check_worker_stuck(
    _task_id: str,
    _subtask_id: str,
    _issue_hash: str,
    current_failures: int,
) -> tuple[bool, str]:
    """Check if worker is stuck on the same issue.

    Args:
        task_id: Task ID
        subtask_id: Subtask ID
        issue_hash: Hash of the normalized error
        current_failures: Number of times this issue has occurred

    Returns:
        (should_escalate, escalation_level) tuple
    """
    if current_failures >= QA_WORKER_STUCK_THRESHOLD:
        return True, "supervisor"
    return False, "worker"
