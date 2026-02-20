"""Notification delivery via Web Push.

Routes notifications to registered push subscriptions based on severity.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from app.storage import push_subscriptions

from . import web_push

logger = logging.getLogger(__name__)

# prevent background tasks from being garbage-collected
_background_tasks: set[asyncio.Task[None]] = set()

FRONTEND_URL = os.getenv("SUMMITFLOW_FRONTEND_URL", "https://dev.summitflow.dev")
AGENT_HUB_URL = os.getenv("AGENT_HUB_FRONTEND_URL", "https://agent.summitflow.dev")

# Severities that trigger push delivery (info stays in-app only)
_PUSH_SEVERITIES = {"critical", "error", "warning"}


def _build_task_url(notification: dict[str, Any]) -> str:
    """Build the task deep-link URL."""
    task_id = notification.get("task_id")
    return f"{FRONTEND_URL}/tasks/{task_id}" if task_id else FRONTEND_URL


async def deliver(notification: dict[str, Any]) -> None:
    """Route a notification to Web Push delivery.

    Severity routing:
        critical/error/warning → Web Push to all registered devices
        info                   → DB only (no push)

    Args:
        notification: Notification dict from storage layer (must have
            'severity', 'title', 'message', and optionally 'task_id').
    """
    severity: str = notification.get("severity", "info")

    if severity not in _PUSH_SEVERITIES:
        return

    subs = await asyncio.to_thread(push_subscriptions.get_all_subscriptions)
    if not subs:
        return

    task_url = _build_task_url(notification)
    payload = {
        "title": notification.get("title", "SummitFlow"),
        "body": notification.get("message", ""),
        "url": task_url,
        "tag": notification.get("id", ""),
        "severity": severity,
        "task_id": notification.get("task_id"),
    }

    sent_count = 0
    for sub in subs:
        sent = await web_push.send(subscription=sub, payload=payload)
        if sent:
            sent_count += 1
            task = asyncio.ensure_future(
                asyncio.to_thread(push_subscriptions.touch_subscription, sub["endpoint"])
            )
            _background_tasks.add(task)
            task.add_done_callback(_background_tasks.discard)

    if sent_count > 0:
        logger.debug(
            "Delivered notification %s via web push (%d devices)",
            notification.get("id"),
            sent_count,
        )
