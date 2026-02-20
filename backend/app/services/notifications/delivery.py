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
    SUMMITFLOW_CLIENT_SECRET,
    SUMMITFLOW_REQUEST_SOURCE,
)

logger = logging.getLogger(__name__)

FRONTEND_URL = os.getenv("SUMMITFLOW_FRONTEND_URL", "https://dev.summitflow.dev")

# Severities that trigger push delivery (info stays in-app only)
_PUSH_SEVERITIES = {"critical", "error", "warning"}


def _build_task_url(notification: dict[str, Any]) -> str:
    """Build deep-link URL that opens Johnny chat with notification context."""
    params = []
    if notification.get("task_id"):
        params.append(f"task_id={notification['task_id']}")
    if notification.get("id"):
        params.append(f"notification_id={notification['id']}")
    if params:
        return f"{FRONTEND_URL}/chat?{'&'.join(params)}"
    return FRONTEND_URL


async def deliver(notification: dict[str, Any]) -> None:
    """Route a notification to Agent Hub push delivery.

    Severity routing:
        critical/error/warning → Web Push via Agent Hub
        info                   → DB only (no push)

    Args:
        notification: Notification dict from storage layer (must have
            'severity', 'title', 'message', and optionally 'task_id').
    """
    severity: str = notification.get("severity", "info")

    if severity not in _PUSH_SEVERITIES:
        return

    task_url = _build_task_url(notification)
    payload = {
        "title": notification.get("title", "SummitFlow"),
        "body": notification.get("message", ""),
        "url": task_url,
        "tag": notification.get("id", ""),
        "severity": severity,
        "task_id": notification.get("task_id"),
        "notification_id": notification.get("id"),
        "project_id": "summitflow",
    }

    try:
        headers = {
            "X-Client-Id": SUMMITFLOW_CLIENT_ID or "",
            "X-Client-Secret": SUMMITFLOW_CLIENT_SECRET or "",
            "X-Request-Source": SUMMITFLOW_REQUEST_SOURCE,
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{AGENT_HUB_URL}/api/push/send",
                json=payload,
                headers=headers,
            )
            if resp.status_code == 200:
                data = resp.json()
                delivered = data.get("delivered", 0)
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
                    resp.text[:200],
                )
    except Exception:
        logger.exception("Failed to deliver notification via Agent Hub push")
