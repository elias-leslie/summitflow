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

# Redis keys and TTL
_REDIS_KEY = "johnny:health:last_status"
_REDIS_TTL = 300  # 5 minutes — stale after this, re-notify on next check

# Health status values
_STATUS_UNHEALTHY = "unhealthy"
_STATUS_DEGRADED = "degraded"
_STATUS_HEALTHY = "healthy"

# Action values
_ACTION_NO_CHANGE = "no_change"
_ACTION_TRANSITION_PREFIX = "transition:"

# Notification constants
_PROJECT_ID = "summitflow"
_NOTIFICATION_TYPE = "system"

# Component labels
_COMPONENT_DATABASE = "Database"
_COMPONENT_CACHE = "Cache"
_LABEL_UNAVAILABLE = "unavailable"

# State transition severity mapping
_TRANSITION_SEVERITY: dict[str, str] = {
    _STATUS_UNHEALTHY: "error",
    _STATUS_DEGRADED: "warning",
    _STATUS_HEALTHY: "info",  # Recovery — info (no push)
}


def _determine_overall_status(db_health: object, cache_health: object) -> str:
    """Determine the overall system status from individual component statuses."""
    db_status = getattr(db_health, "status", _STATUS_HEALTHY)
    cache_status = getattr(cache_health, "status", _STATUS_HEALTHY)

    if db_status == _STATUS_UNHEALTHY or cache_status == _STATUS_UNHEALTHY:
        return _STATUS_UNHEALTHY
    if db_status == _STATUS_DEGRADED or cache_status == _STATUS_DEGRADED:
        return _STATUS_DEGRADED
    return _STATUS_HEALTHY


def _handle_transition(
    previous_status: str,
    current_status: str,
    db_health: object,
    cache_health: object,
) -> str:
    """Handle a health state transition, sending notification and returning action."""
    action = f"{_ACTION_TRANSITION_PREFIX}{previous_status}->{current_status}"
    _send_transition_notification(previous_status, current_status, db_health, cache_health)
    return action


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

    current_status = _determine_overall_status(db_health, cache_health)
    previous_status = _get_last_status()

    action = _ACTION_NO_CHANGE
    if previous_status and previous_status != current_status:
        action = _handle_transition(previous_status, current_status, db_health, cache_health)

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


def _build_unhealthy_notification(
    db_health: object, cache_health: object
) -> tuple[str, str]:
    """Build title and message for an unhealthy transition."""
    components = []
    if getattr(db_health, "status", "") == _STATUS_UNHEALTHY:
        msg = getattr(db_health, "message", _LABEL_UNAVAILABLE)
        components.append(f"{_COMPONENT_DATABASE}: {msg}")
    if getattr(cache_health, "status", "") == _STATUS_UNHEALTHY:
        msg = getattr(cache_health, "message", _LABEL_UNAVAILABLE)
        components.append(f"{_COMPONENT_CACHE}: {msg}")
    detail = "; ".join(components) if components else "Unknown component"
    title = "System unhealthy"
    message = f"Something's down. {detail}. I'll keep checking."
    return title, message


def _build_degraded_notification(
    db_health: object, cache_health: object
) -> tuple[str, str]:
    """Build title and message for a degraded transition."""
    components = []
    if getattr(db_health, "status", "") == _STATUS_DEGRADED:
        db_ms = getattr(db_health, "response_time_ms", "?")
        components.append(f"{_COMPONENT_DATABASE} responding slowly ({db_ms}ms)")
    if getattr(cache_health, "status", "") == _STATUS_DEGRADED:
        cache_ms = getattr(cache_health, "response_time_ms", "?")
        components.append(f"{_COMPONENT_CACHE} responding slowly ({cache_ms}ms)")
    detail = "; ".join(components) if components else "Elevated latency"
    title = "System degraded"
    message = f"Heads up — {detail}. Keeping an eye on it."
    return title, message


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

    if current == _STATUS_UNHEALTHY:
        title, message = _build_unhealthy_notification(db_health, cache_health)
    elif current == _STATUS_DEGRADED:
        title, message = _build_degraded_notification(db_health, cache_health)
    else:
        # Recovery
        title = "System recovered"
        message = f"All clear — back to healthy from {previous}."

    try:
        create_notification(
            project_id=_PROJECT_ID,
            notification_type=_NOTIFICATION_TYPE,
            title=title,
            message=message,
            severity=severity,
            metadata={"johnny": True, "health_transition": f"{previous}->{current}"},
        )
    except Exception:
        logger.exception("Failed to create health transition notification")
