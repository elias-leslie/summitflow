"""Periodic health monitor with Johnny-branded notifications.

Checks system health and sends push notifications on state transitions.
Tracks last-known state in Redis to detect changes.
"""

from __future__ import annotations

import json
import logging
import time
from typing import cast

import redis

from ...config import REDIS_URL
from ...storage.notifications import NotificationSeverity, create_notification

logger = logging.getLogger(__name__)

_REDIS_KEY = "johnny:health:last_status"
_REDIS_TTL = 300  # 5 minutes — stale after this, re-notify on next check

# State transition severity mapping
_TRANSITION_SEVERITY: dict[str, str] = {
    "unhealthy": "error",
    "degraded": "warning",
    "healthy": "info",  # Recovery — info (no push)
}

_PROJECT_ID = "summitflow"


def check_and_notify() -> dict[str, str]:
    """Check system health and notify on state transitions.

    Returns:
        Dict with current status and action taken.
    """
    from ...main import _check_cache_health, _check_database_health

    start = time.time()
    db_health = _check_database_health()
    cache_health = _check_cache_health()
    check_ms = round((time.time() - start) * 1000, 1)

    # Determine overall status
    if db_health.status == "unhealthy" or cache_health.status == "unhealthy":
        current_status = "unhealthy"
    elif db_health.status == "degraded" or cache_health.status == "degraded":
        current_status = "degraded"
    else:
        current_status = "healthy"

    # Get last known status from Redis
    previous_status = _get_last_status()

    # Detect transition
    action = "no_change"
    if previous_status and previous_status != current_status:
        action = f"transition:{previous_status}->{current_status}"
        _send_transition_notification(
            previous_status,
            current_status,
            db_health,
            cache_health,
        )

    # Store current status
    _set_last_status(current_status)

    logger.debug(
        "Health check: %s (db=%s, cache=%s, %sms)",
        current_status,
        db_health.status,
        cache_health.status,
        check_ms,
    )

    return {
        "status": current_status,
        "action": action,
        "db": db_health.status,
        "cache": cache_health.status,
        "check_ms": str(check_ms),
    }


def _get_last_status() -> str | None:
    """Read last known health status from Redis."""
    try:
        r = redis.from_url(f"{REDIS_URL}/1")
        raw = r.get(_REDIS_KEY)
        if raw:
            data = json.loads(raw)
            return cast(str, data.get("status"))
    except Exception:
        logger.debug("Could not read last health status from Redis")
    return None


def _set_last_status(status: str) -> None:
    """Store current health status in Redis."""
    try:
        r = redis.from_url(f"{REDIS_URL}/1")
        r.set(_REDIS_KEY, json.dumps({"status": status}), ex=_REDIS_TTL)
    except Exception:
        logger.debug("Could not store health status in Redis")


def _send_transition_notification(
    previous: str,
    current: str,
    db_health: object,
    cache_health: object,
) -> None:
    """Send a Johnny-branded notification for a health state transition."""
    severity: NotificationSeverity = cast(
        NotificationSeverity, _TRANSITION_SEVERITY.get(current, "warning")
    )

    if current == "unhealthy":
        # Identify which component(s) are down
        components = []
        if getattr(db_health, "status", "") == "unhealthy":
            components.append(f"Database: {getattr(db_health, 'message', 'unavailable')}")
        if getattr(cache_health, "status", "") == "unhealthy":
            components.append(f"Cache: {getattr(cache_health, 'message', 'unavailable')}")
        detail = "; ".join(components) if components else "Unknown component"
        title = "System unhealthy"
        message = f"Something's down. {detail}. I'll keep checking."
    elif current == "degraded":
        components = []
        if getattr(db_health, "status", "") == "degraded":
            db_ms = getattr(db_health, "response_time_ms", "?")
            components.append(f"Database responding slowly ({db_ms}ms)")
        if getattr(cache_health, "status", "") == "degraded":
            cache_ms = getattr(cache_health, "response_time_ms", "?")
            components.append(f"Cache responding slowly ({cache_ms}ms)")
        detail = "; ".join(components) if components else "Elevated latency"
        title = "System degraded"
        message = f"Heads up — {detail}. Keeping an eye on it."
    else:
        # Recovery
        title = "System recovered"
        message = f"All clear — back to healthy from {previous}."

    try:
        create_notification(
            project_id=_PROJECT_ID,
            notification_type="system",
            title=title,
            message=message,
            severity=severity,
            metadata={"johnny": True, "health_transition": f"{previous}->{current}"},
        )
    except Exception:
        logger.exception("Failed to create health transition notification")
