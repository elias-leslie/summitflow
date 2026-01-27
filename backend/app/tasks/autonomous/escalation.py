"""3-2-1 Escalation pattern for autonomous execution.

Escalation tiers:
- Worker: 3 failures on same issue -> escalate to supervisor
- Supervisor: 2 failures -> escalate to human review
- Human: Review with recommendation statement
"""

from __future__ import annotations

from typing import Any

from celery import Task, shared_task

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


@shared_task(bind=True, name="autonomous.supervisor_guidance")
def supervisor_guidance(
    self: Task[..., dict[str, Any]],
    task_id: str,
    subtask_id: str,
    issue_description: str,
    failure_count: int,
) -> dict[str, Any]:
    """Get supervisor guidance for a stuck worker.

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
        return _escalate_to_human(task_id, subtask_id, issue_description, failure_count)

    prompt = f"""A worker agent is stuck on this issue. Provide GUIDANCE only, not implementation.

Task ID: {task_id}
Subtask: {subtask_id}
Issue: {issue_description}
Worker Attempts: {failure_count}

Analyze the issue and provide:
1. Root cause analysis
2. Suggested approach to fix
3. Key considerations

DO NOT write code. Guide the worker on HOW to approach this."""

    try:
        client = get_sync_client()
        response = client.complete(
            messages=[{"role": "user", "content": prompt}],
            agent_slug="supervisor",
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
        return _escalate_to_human(task_id, subtask_id, issue_description, failure_count)


def _escalate_to_human(
    task_id: str,
    subtask_id: str,
    issue_description: str,
    attempts: int,
) -> dict[str, Any]:
    """Escalate to human review with problem/solution recommendation."""
    logger.info("Escalating to human review", task_id=task_id, subtask_id=subtask_id)

    prompt = f"""This issue needs human review. Generate a clear problem/solution recommendation.

Task ID: {task_id}
Subtask: {subtask_id}
Issue: {issue_description}
Total Attempts: {attempts}

Provide a structured recommendation:
1. PROBLEM: Clear statement of what's wrong
2. ANALYSIS: Root cause and why automation couldn't solve it
3. RECOMMENDATION: Proposed direction for human to approve/modify"""

    recommendation = f"Issue in {subtask_id}: {issue_description}"

    try:
        client = get_sync_client()
        response = client.complete(
            messages=[{"role": "user", "content": prompt}],
            agent_slug="supervisor",
        )
        recommendation = response.content
    except Exception as e:
        logger.warning("Failed to generate recommendation", error=str(e))

    task_store.update_task_status(task_id, "human_review")
    _add_escalation_message(task_id, subtask_id, recommendation, attempts)

    return {
        "task_id": task_id,
        "subtask_id": subtask_id,
        "status": "escalated_to_human",
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
