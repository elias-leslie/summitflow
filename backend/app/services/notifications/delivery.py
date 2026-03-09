"""Notification delivery via Agent Hub push service.

Routes notifications to Agent Hub's shared push delivery based on severity.
"""

from __future__ import annotations

import logging
import os
from typing import Any
from urllib.parse import urlencode

import httpx

from app.services._agent_hub_config import (
    AGENT_HUB_URL,
    build_agent_hub_headers,
)

logger = logging.getLogger(__name__)

FRONTEND_URL = os.getenv("SUMMITFLOW_FRONTEND_URL", "https://dev.summitflow.dev")

_PUSH_SEVERITIES = {"critical", "error", "warning"}
_DEFAULT_TITLE = "SummitFlow"
_PUSH_ENDPOINT = "/api/push/send"
_HTTP_TIMEOUT = 10.0
_HTTP_OK = 200
_LOG_TEXT_LIMIT = 200
_DEFAULT_PROJECT_ID = "summitflow"
_PUSH_DELIVERED_KEY = "delivered"


def _log_push_response(resp: httpx.Response, notification_id: Any) -> None:
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
    """Build the push payload dict for Agent Hub delivery."""
    project_id = notification.get("project_id", _DEFAULT_PROJECT_ID)
    return {
        "title": notification.get("title", _DEFAULT_TITLE),
        "body": notification.get("message", ""),
        "url": _build_task_url(notification),
        "tag": notification.get("id", ""),
        "severity": notification.get("severity", "info"),
        "task_id": notification.get("task_id"),
        "notification_id": notification.get("id"),
        "project_id": project_id,
    }


async def deliver(notification: dict[str, Any]) -> None:
    """Route a notification to Agent Hub push delivery.

    Severity routing:
        critical/error/warning → Web Push via Agent Hub
        info                   → DB only (no push)

    Args:
        notification: Notification dict from storage layer (must have
            'severity', 'title', 'message', and optionally 'task_id').
    """
    if notification.get("severity", "info") not in _PUSH_SEVERITIES:
        return

    headers = build_agent_hub_headers()
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            resp = await client.post(
                f"{AGENT_HUB_URL}{_PUSH_ENDPOINT}",
                json=_build_payload(notification),
                headers=headers,
            )
        _log_push_response(resp, notification.get("id"))
    except Exception:
        logger.exception("Failed to deliver notification via Agent Hub push")
