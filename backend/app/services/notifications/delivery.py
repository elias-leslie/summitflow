"""Notification delivery via Agent Hub Telegram.

Critical and error notifications go to the household Telegram chat through
Agent Hub's ``POST /api/notifications/telegram``. The Agent Hub SDK has no
method for that endpoint, so this uses the standard direct-HTTP header path.
"""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlencode

import httpx

from app.services._agent_hub_config import (
    AGENT_HUB_URL,
    build_agent_hub_headers,
)

from ...logging_config import get_logger

logger = get_logger(__name__)

FRONTEND_URL = os.getenv("SUMMITFLOW_FRONTEND_URL", "http://localhost:3001")

_TELEGRAM_SEVERITIES = {"critical", "error"}
_FORCE_TELEGRAM_KEY = "force_telegram"
_DEFAULT_TITLE = "SummitFlow"
_SOURCE = "summitflow"

# Short display names for project IDs in notification titles
_PROJECT_DISPLAY: dict[str, str] = {
    "summitflow": "SF",
    "agent-hub": "AH",
    "portfolio-ai": "PA",
    "a-term": "AT",
    "monkey-fight": "MF",
    "infrastructure": "Infra",
}
_TELEGRAM_ENDPOINT = "/api/notifications/telegram"
_HTTP_TIMEOUT = 10.0
_HTTP_OK = 200
_LOG_TEXT_LIMIT = 200
_TITLE_LIMIT = 200
_BODY_LIMIT = 8000
_DEFAULT_PROJECT_ID = "summitflow"


def _project_display_name(project_id: str) -> str:
    """Return a short display slug for the project, or title-cased fallback."""
    return _PROJECT_DISPLAY.get(project_id, project_id.replace("-", " ").title()[:12])


def _log_telegram_response(resp: httpx.Response, notification_id: str) -> None:
    """Log the outcome of an Agent Hub Telegram response."""
    if resp.status_code != _HTTP_OK:
        logger.warning(
            "Agent Hub Telegram send failed for %s: %s %s",
            notification_id,
            resp.status_code,
            resp.text[:_LOG_TEXT_LIMIT],
        )
        return
    status = resp.json().get("status")
    if status == "sent":
        logger.debug("Delivered notification %s via Agent Hub Telegram", notification_id)
    else:
        logger.warning(
            "Notification %s accepted by Agent Hub but Telegram status was %s",
            notification_id,
            status,
        )


def _build_task_url(notification: dict[str, Any]) -> str:
    """Build deep-link URL that opens Johnny chat with notification context."""
    params: dict[str, str] = {}
    project_id = notification.get("project_id")
    if project_id:
        params["project_id"] = str(project_id)
    if notification.get("task_id"):
        params["task_id"] = str(notification["task_id"])
    if notification.get("id"):
        params["notification_id"] = str(notification["id"])
    return f"{FRONTEND_URL}/chat?{urlencode(params)}" if params else FRONTEND_URL


def _build_payload(notification: dict[str, Any]) -> dict[str, Any]:
    """Build the Agent Hub Telegram payload (``title``, ``body``, ``severity``, ``source``).

    The title carries an explicit severity prefix such as ``[CRITICAL]`` or
    ``[ERROR]`` plus the short project slug.
    """
    project_id = notification.get("project_id") or _DEFAULT_PROJECT_ID
    severity = notification.get("severity") or "info"
    metadata = notification.get("metadata") or {}

    raw_title = notification.get("title") or _DEFAULT_TITLE
    title = f"[{severity.upper()}] [{_project_display_name(project_id)}] {raw_title}"

    lines = [notification.get("message") or raw_title]
    if metadata.get("blocker_summary"):
        lines.append(f"Blocker: {metadata['blocker_summary'][:120]}")
    if metadata.get("recommendation"):
        lines.append(f"Next: {metadata['recommendation'][:120]}")
    if notification.get("task_id"):
        lines.append(f"Task: {notification['task_id']}")
    lines.append(_build_task_url(notification))

    return {
        "title": title[:_TITLE_LIMIT],
        "body": "\n".join(lines)[:_BODY_LIMIT],
        "severity": severity,
        "source": _SOURCE,
    }


def should_deliver(notification: dict[str, Any]) -> bool:
    """Return True when the notification is routed to Telegram."""
    metadata = notification.get("metadata") or {}
    return notification.get("severity") in _TELEGRAM_SEVERITIES or bool(
        metadata.get(_FORCE_TELEGRAM_KEY)
    )


async def deliver(notification: dict[str, Any]) -> None:
    """Route a notification to Agent Hub Telegram delivery.

    Severity routing:
        critical/error → Telegram via Agent Hub
        warning/info   → DB only unless metadata.force_telegram is set

    The force_telegram metadata flag lets callers opt specific warnings into
    Telegram (e.g., supervisor escalations) without inflating severity.
    """
    if not should_deliver(notification):
        return

    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            resp = await client.post(
                f"{AGENT_HUB_URL}{_TELEGRAM_ENDPOINT}",
                json=_build_payload(notification),
                headers=build_agent_hub_headers(),
            )
        _log_telegram_response(resp, notification.get("id") or "")
    except Exception:
        logger.exception("Failed to deliver notification via Agent Hub Telegram")
