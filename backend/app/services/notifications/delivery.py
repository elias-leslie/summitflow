"""Notification delivery via Agent Hub push service.

Routes notifications to Agent Hub's shared push delivery based on severity.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from app.services._agent_hub_config import (
    AGENT_HUB_URL,
    SUMMITFLOW_CLIENT_ID,
    SUMMITFLOW_REQUEST_SOURCE,
)

logger = logging.getLogger(__name__)

FRONTEND_URL = os.getenv("SUMMITFLOW_FRONTEND_URL", "https://dev.summitflow.dev")

_PUSH_SEVERITIES = {"critical", "error", "warning"}
_DEFAULT_TITLE = "SummitFlow"
_PROJECT_ID = "summitflow"
_PUSH_ENDPOINT = "/api/push/send"
_HTTP_TIMEOUT = 10.0
_HTTP_OK = 200
_LOG_TEXT_LIMIT = 200


def _build_task_url(notification: dict[str, Any]) -> str:
    """Build deep-link URL that opens Johnny chat with notification context."""
    params = []
    if notification.get("task_id"):
        params.append(f"task_id={notification['task_id']}")
    if notification.get("id"):
        params.append(f"notification_id={notification['id']}")
    return f"{FRONTEND_URL}/chat?{'&'.join(params)}" if params else FRONTEND_URL


def _build_payload(notification: dict[str, Any]) -> dict[str, Any]:
    """Build the push payload dict for Agent Hub delivery."""
    return {
        "title": notification.get("title", _DEFAULT_TITLE),
        "body": notification.get("message", ""),
        "url": _build_task_url(notification),
        "tag": notification.get("id", ""),
        "severity": notification.get("severity", "info"),
        "task_id": notification.get("task_id"),
        "notification_id": notification.get("id"),
        "project_id": _PROJECT_ID,
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

    headers = {"X-Client-Id": SUMMITFLOW_CLIENT_ID or "", "X-Request-Source": SUMMITFLOW_REQUEST_SOURCE}
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            resp = await client.post(
                f"{AGENT_HUB_URL}{_PUSH_ENDPOINT}",
                json=_build_payload(notification),
                headers=headers,
            )
            if resp.status_code == _HTTP_OK:
                delivered = resp.json().get("delivered", 0)
                if delivered > 0:
                    logger.debug(
                        "Delivered notification %s via Agent Hub push (%d devices)",
                        notification.get("id"),
                        delivered,
                    )
            else:
                logger.warning(
                    "Agent Hub push send failed: %s %s",
                    resp.status_code,
                    resp.text[:_LOG_TEXT_LIMIT],
                )
    except Exception:
        logger.exception("Failed to deliver notification via Agent Hub push")
