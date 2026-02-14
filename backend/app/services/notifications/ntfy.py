"""ntfy push notification client.

Sends notifications to a self-hosted ntfy server via HTTP POST.
Backend publishes to localhost — no auth needed (CF Access + ntfy auth
protect the public endpoint for phone subscriptions).
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# Reusable timeout — ntfy is localhost, should be fast
_TIMEOUT = httpx.Timeout(5.0, connect=2.0)


async def send(
    message: str,
    title: str = "",
    priority: int | None = None,
    tags: list[str] | None = None,
    actions: list[dict[str, Any]] | None = None,
    click_url: str | None = None,
) -> bool:
    """Send a push notification via ntfy.

    Never raises — logs errors and returns False.

    Args:
        message: Notification body text.
        title: Optional title (bold header in ntfy app).
        priority: 1 (min) to 5 (max urgent). Uses config default if None.
        tags: Optional emoji tags (e.g. ["warning", "rotating_light"]).
        actions: Optional action buttons (ntfy action objects).
        click_url: URL opened when tapping the notification body.

    Returns:
        True if sent successfully, False otherwise.
    """
    if not settings.ntfy_enabled:
        return False

    url = f"{settings.ntfy_url}/{settings.ntfy_topic}"
    payload: dict[str, Any] = {
        "message": message,
        "priority": priority or settings.ntfy_default_priority,
    }
    if title:
        payload["title"] = title
    if tags:
        payload["tags"] = tags
    if actions:
        payload["actions"] = actions
    if click_url:
        payload["click"] = click_url

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
        return True
    except Exception:
        logger.exception("Failed to send ntfy notification")
        return False
