"""Channel-agnostic notification dispatcher.

Routes notifications to delivery channels based on severity.
Supports Web Push (PWA) and ntfy (legacy).
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from . import ntfy, web_push

logger = logging.getLogger(__name__)

FRONTEND_URL = os.getenv("SUMMITFLOW_FRONTEND_URL", "https://dev.summitflow.dev")
AGENT_HUB_URL = os.getenv("AGENT_HUB_FRONTEND_URL", "https://agent.summitflow.dev")

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


def _build_task_url(notification: dict[str, Any]) -> str:
    """Build the task deep-link URL."""
    task_id = notification.get("task_id")
    return f"{FRONTEND_URL}/tasks/{task_id}" if task_id else FRONTEND_URL


def _build_task_actions(notification: dict[str, Any]) -> list[dict[str, Any]]:
    """Build ntfy action buttons for task-related notifications.

    Uses 'view' actions (opens URL in browser) rather than headless 'http'
    actions, because the API is behind CF Access — the browser already has
    the CF_Authorization cookie, so view actions work seamlessly.
    """
    task_id = notification.get("task_id")
    if not task_id:
        return []

    actions = [
        {
            "action": "view",
            "label": "Details",
            "url": f"{FRONTEND_URL}/tasks/{task_id}",
            "clear": True,
        },
    ]

    # Add "Chat with Johnny" button for Johnny-branded notifications
    metadata = notification.get("metadata") or {}
    if metadata.get("johnny"):
        actions.append({
            "action": "view",
            "label": "Chat",
            "url": f"{AGENT_HUB_URL}/chat?agent=johnny&task={task_id}",
            "clear": True,
        })

    return actions


async def _deliver_web_push(notification: dict[str, Any]) -> int:
    """Send notification to all registered Web Push subscriptions.

    Returns number of successful deliveries.
    """
    from app.storage import push_subscriptions

    subs = await asyncio.to_thread(push_subscriptions.get_all_subscriptions)
    if not subs:
        return 0

    task_url = _build_task_url(notification)
    payload = {
        "title": notification.get("title", "SummitFlow"),
        "body": notification.get("message", ""),
        "url": task_url,
        "tag": notification.get("id", ""),
        "severity": notification.get("severity", "info"),
        "task_id": notification.get("task_id"),
    }

    sent_count = 0
    for sub in subs:
        sent = await web_push.send(subscription=sub, payload=payload)
        if sent:
            sent_count += 1
            # Update last_used_at in background
            asyncio.ensure_future(
                asyncio.to_thread(push_subscriptions.touch_subscription, sub["endpoint"])
            )

    return sent_count


async def deliver(notification: dict[str, Any]) -> None:
    """Route a notification to configured delivery channels.

    Severity routing:
        critical/error → push (Web Push + ntfy)
        warning        → push (Web Push + ntfy)
        info           → DB only (no push)

    Sends to both Web Push and ntfy in parallel. Either or both
    may be disabled — delivery is best-effort.

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
    click_url = _build_task_url(notification)

    # Send to both channels in parallel
    web_push_task = _deliver_web_push(notification)
    ntfy_task = ntfy.send(
        message=notification.get("message", ""),
        title=notification.get("title", "SummitFlow"),
        priority=priority,
        tags=tags,
        actions=actions or None,
        click_url=click_url,
    )

    web_push_count, ntfy_sent = await asyncio.gather(
        web_push_task, ntfy_task, return_exceptions=True
    )

    nid = notification.get("id")
    if isinstance(web_push_count, int) and web_push_count > 0:
        logger.debug("Delivered notification %s via web push (%d devices)", nid, web_push_count)
    if ntfy_sent is True:
        logger.debug("Delivered notification %s via ntfy", nid)
