"""Notification delivery via Agent Hub push service.

Routes notifications to Agent Hub's shared push delivery based on severity.
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

FRONTEND_URL = os.getenv("SUMMITFLOW_FRONTEND_URL", "https://dev.summitflow.dev")

_PUSH_SEVERITIES = {"critical", "error"}
_DEFAULT_TITLE = "SummitFlow"

# Short display names for project IDs in notification titles
_PROJECT_DISPLAY: dict[str, str] = {
    "summitflow": "SF",
    "agent-hub": "AH",
    "portfolio-ai": "PA",
    "terminal": "TM",
    "monkey-fight": "MF",
    "infrastructure": "Infra",
}
_PUSH_ENDPOINT = "/api/push/send"
_HTTP_TIMEOUT = 10.0
_HTTP_OK = 200
_LOG_TEXT_LIMIT = 200
_DEFAULT_PROJECT_ID = "summitflow"
_PUSH_DELIVERED_KEY = "delivered"


def _project_display_name(project_id: str) -> str:
    """Return a short display slug for the project, or title-cased fallback."""
    return _PROJECT_DISPLAY.get(project_id, project_id.replace("-", " ").title()[:12])


def _log_push_response(resp: httpx.Response, notification_id: str) -> None:
    """Log outcome of an Agent Hub push response."""
    if resp.status_code != _HTTP_OK:
        logger.warning(
            "Agent Hub push send failed: %s %s",
            resp.status_code,
            resp.text[:_LOG_TEXT_LIMIT],
        )
        return
    delivered = resp.json().get(_PUSH_DELIVERED_KEY, 0)
    if delivered > 0:
        logger.debug(
            "Delivered notification %s via Agent Hub push (%d devices)",
            notification_id,
            delivered,
        )
    else:
        logger.warning(
            "Notification %s accepted by Agent Hub but delivered to 0 devices",
            notification_id,
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
    """Build the push payload dict for Agent Hub delivery.

    Constructs a rich payload so lock-screen notifications show useful context
    without requiring the user to unlock the device.
    """
    project_id = notification.get("project_id", _DEFAULT_PROJECT_ID)
    severity = notification.get("severity", "info")
    task_id = notification.get("task_id")
    metadata = notification.get("metadata") or {}
    notif_type = notification.get("type", "")

    # --- Rich title: prefix with project slug for multi-project awareness ---
    raw_title = notification.get("title", _DEFAULT_TITLE)
    project_slug = _project_display_name(project_id)
    title = f"[{project_slug}] {raw_title}" if project_slug else raw_title

    # --- Rich body: add actionable detail beyond the generic message ---
    body = notification.get("message", "")
    extras: list[str] = []
    if metadata.get("blocker_summary"):
        extras.append(f"Blocker: {metadata['blocker_summary'][:120]}")
    if metadata.get("recommendation"):
        extras.append(f"Next: {metadata['recommendation'][:120]}")
    if extras:
        body = f"{body}\n{'  '.join(extras)}"

    return {
        "title": title,
        "body": body,
        "url": _build_task_url(notification),
        "tag": notification.get("id", ""),
        "severity": severity,
        "task_id": task_id,
        "notification_id": notification.get("id"),
        "project_id": project_id,
        "type": notif_type,
    }


async def deliver(notification: dict[str, Any]) -> None:
    """Route a notification to Agent Hub push delivery.

    Severity routing:
        critical/error → Web Push via Agent Hub
        warning/info   → DB only (no push) unless metadata.force_push is set

    The force_push metadata flag lets callers opt specific warnings into push
    delivery (e.g., supervisor escalations) without inflating severity.

    Args:
        notification: Notification dict from storage layer (must have
            'severity', 'title', 'message', and optionally 'task_id').
    """
    severity = notification.get("severity", "info")
    metadata = notification.get("metadata") or {}
    if severity not in _PUSH_SEVERITIES and not metadata.get("force_push"):
        return

    headers = build_agent_hub_headers()
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            resp = await client.post(
                f"{AGENT_HUB_URL}{_PUSH_ENDPOINT}",
                json=_build_payload(notification),
                headers=headers,
            )
        _log_push_response(resp, notification.get("id") or "")
    except Exception:
        logger.exception("Failed to deliver notification via Agent Hub push")
