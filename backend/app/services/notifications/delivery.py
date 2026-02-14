"""Channel-agnostic notification dispatcher.

Routes notifications to delivery channels based on severity.
Currently supports ntfy; designed for future channels (Web Push, etc.).
"""

from __future__ import annotations

import logging
from typing import Any

from . import ntfy

logger = logging.getLogger(__name__)

FRONTEND_URL = "https://dev.summitflow.dev"

# Severity → ntfy priority mapping
_SEVERITY_PRIORITY: dict[str, int] = {
    "critical": 5,
    "error": 5,
    "warning": 3,
}

# ntfy emoji tags per severity
_SEVERITY_TAGS: dict[str, list[str]] = {
    "critical": ["rotating_light"],
    "error": ["x"],
    "warning": ["warning"],
}


def _build_task_actions(notification: dict[str, Any]) -> list[dict[str, Any]]:
    """Build ntfy action buttons for task-related notifications.

    Uses 'view' actions (opens URL in browser) rather than headless 'http'
    actions, because the API is behind CF Access — the browser already has
    the CF_Authorization cookie, so view actions work seamlessly.
    """
    task_id = notification.get("task_id")
    if not task_id:
        return []

    return [
        {
            "action": "view",
            "label": "Details",
            "url": f"{FRONTEND_URL}/tasks/{task_id}",
            "clear": True,
        },
    ]


async def deliver(notification: dict[str, Any]) -> None:
    """Route a notification to configured delivery channels.

    Severity routing:
        critical/error → ntfy priority 5 (urgent push)
        warning        → ntfy priority 3 (normal push)
        info           → DB only (no push)

    Args:
        notification: Notification dict from storage layer (must have
            'severity', 'title', 'message', and optionally 'task_id').
    """
    severity: str = notification.get("severity", "info")

    # Info notifications stay in-app only — no push
    if severity not in _SEVERITY_PRIORITY:
        return

    priority = _SEVERITY_PRIORITY[severity]
    tags = _SEVERITY_TAGS.get(severity)
    actions = _build_task_actions(notification)

    task_id = notification.get("task_id")
    click_url = f"{FRONTEND_URL}/tasks/{task_id}" if task_id else FRONTEND_URL

    sent = await ntfy.send(
        message=notification.get("message", ""),
        title=notification.get("title", "SummitFlow"),
        priority=priority,
        tags=tags,
        actions=actions or None,
        click_url=click_url,
    )

    if sent:
        logger.debug("Delivered notification %s via ntfy", notification.get("id"))
