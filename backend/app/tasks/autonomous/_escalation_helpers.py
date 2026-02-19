"""Helper utilities for the 3-2-1 escalation pattern.

Internal module — import from escalation.py for public API.
"""

from __future__ import annotations

from ...logging_config import get_logger
from ...services.agent_hub_client import get_sync_client
from ...storage import log_task_event

logger = get_logger(__name__)

# Agent and project defaults — single source of truth for magic strings
SUPERVISOR_AGENT_SLUG: str = "supervisor"
DEFAULT_PROJECT_ID: str = "summitflow"
_STEP_OUTPUT_TRUNCATE: int = 300
_GUIDANCE_LOG_TRUNCATE: int = 500


def build_step_context(step_outputs: list[dict[str, str | int | bool]]) -> str:
    """Build formatted context string from failed step outputs.

    Args:
        step_outputs: List of step result dicts from verification.

    Returns:
        Formatted multi-line string, or empty string if no failures.
    """
    details = [
        f"- Step {step.get('step_number')}: {step.get('reason', 'failed')}\n"
        f"  Output: {str(step.get('output', ''))[:_STEP_OUTPUT_TRUNCATE]}"
        for step in step_outputs
        if not step.get("passed")
    ]
    if not details:
        return ""
    return "\n\nFailed step details:\n" + "\n".join(details)


def call_supervisor(
    prompt: str,
    project_id: str | None = None,
) -> str | None:
    """Call the supervisor agent and return its response content.

    Args:
        prompt: The prompt to send to the supervisor.
        project_id: Override project ID; defaults to DEFAULT_PROJECT_ID.

    Returns:
        Response content string, or None on failure.
    """
    try:
        client = get_sync_client()
        response = client.complete(
            messages=[{"role": "user", "content": prompt}],
            agent_slug=SUPERVISOR_AGENT_SLUG,
            project_id=project_id or DEFAULT_PROJECT_ID,
        )
        return str(response.content)
    except Exception as exc:
        logger.warning("Supervisor call failed", error=str(exc))
        return None


def add_escalation_message(
    task_id: str,
    subtask_id: str,
    recommendation: str,
    attempts: int,
) -> None:
    """Log escalation message to the task event log.

    Args:
        task_id: The task ID.
        subtask_id: The stuck subtask ID.
        recommendation: Supervisor recommendation text.
        attempts: Total number of attempts made.
    """
    message = (
        f"ESCALATION REQUIRED\n\n"
        f"Subtask: {subtask_id}\n"
        f"Total Attempts: {attempts}\n\n"
        f"{recommendation}\n\n"
        f"Please review and approve a direction to proceed."
    )
    log_task_event(task_id, message)
    logger.info("Escalation message added", task_id=task_id)


def log_guidance(task_id: str, subtask_id: str, guidance: str) -> None:
    """Log supervisor guidance to the task event log.

    Args:
        task_id: The task ID.
        subtask_id: The subtask that received guidance.
        guidance: The guidance text.
    """
    log_task_event(
        task_id,
        f"Supervisor guidance for {subtask_id}:\n{guidance[:_GUIDANCE_LOG_TRUNCATE]}",
    )
