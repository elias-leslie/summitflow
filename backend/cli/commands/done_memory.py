"""Memory system integration for done command.

Handles task outcome reporting to Agent Hub.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _build_outcome_payload(
    task_id: str,
    succeeded: bool,
    project_id: str | None,
    started_at: str | None,
) -> dict[str, str | bool]:
    """Build payload for task outcome report."""
    payload: dict[str, str | bool] = {"task_id": task_id, "succeeded": succeeded}
    if project_id:
        payload["project_id"] = project_id
    if started_at:
        payload["started_at"] = started_at
    return payload


def report_task_outcome(
    task_id: str,
    *,
    succeeded: bool,
    project_id: str | None = None,
    started_at: str | None = None,
) -> None:
    """Report task outcome to Agent Hub memory system (fire-and-forget).

    Credits loaded memories when tasks succeed, enabling utility_score tracking.
    Passes project_id + started_at for fallback session lookup when external_id
    not set (common for CC interactive sessions that claim tasks after start).
    Non-blocking — failures are logged but never block task completion.
    """
    try:
        from ._api_paths import MEMORY_TASK_OUTCOME_PATH
        from .memory_api import agent_hub_request

        payload = _build_outcome_payload(task_id, succeeded, project_id, started_at)
        agent_hub_request(
            "POST",
            MEMORY_TASK_OUTCOME_PATH,
            json=payload,
            tool_name="st done",
        )
    except Exception:
        logger.debug("Failed to report task outcome for %s", task_id)
