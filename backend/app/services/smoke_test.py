"""Service health smoke tests.

Hits local health endpoints and reports failures.
Called by the prod-smoke-test cron workflow every 15 minutes.
Only sends push notifications on state transitions (healthy->unhealthy)
to avoid notification spam.
"""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.request import Request, urlopen

from ..logging_config import get_logger
from .redis_pool import get_redis

logger = get_logger(__name__)

_REDIS_KEY = "smoke_test:last_status"
_REDIS_TTL = 3600  # 1 hour — re-notify if still failing after TTL expires

# Health endpoints — configurable via env vars for Docker (service names) vs native (localhost)
HEALTH_URLS: dict[str, str] = {
    "summitflow": os.getenv("SUMMITFLOW_HEALTH_URL", "http://localhost:8001/health"),
    "agent-hub": os.getenv("AGENT_HUB_HEALTH_URL", "http://localhost:8003/health"),
    "portfolio-ai": os.getenv("PORTFOLIO_HEALTH_URL", "http://localhost:8000/health"),
    "terminal": os.getenv("TERMINAL_HEALTH_URL", "http://localhost:8002/health"),
}


def check_health(project_id: str, url: str) -> dict[str, Any]:
    """Check a single health endpoint via HTTP."""
    try:
        req = Request(url, method="GET")
        with urlopen(req, timeout=10) as resp:
            ok = resp.status == 200
            return {
                "project": project_id,
                "url": url,
                "ok": ok,
                "status": "healthy" if ok else f"http_{resp.status}",
            }
    except Exception as e:
        return {
            "project": project_id,
            "url": url,
            "ok": False,
            "status": f"error: {type(e).__name__}: {e}",
        }


def _get_last_status() -> str | None:
    """Read last known smoke test status from Redis."""
    try:
        raw = get_redis().get(_REDIS_KEY)
        if raw:
            data = json.loads(raw)
            return data.get("status")
    except Exception:
        logger.debug("Could not read last smoke test status from Redis")
    return None


def _set_last_status(status: str) -> None:
    """Store current smoke test status in Redis."""
    try:
        get_redis().set(_REDIS_KEY, json.dumps({"status": status}), ex=_REDIS_TTL)
    except Exception:
        logger.debug("Could not store smoke test status in Redis")


def run_all_smoke_tests() -> dict[str, Any]:
    """Run all health checks. Returns summary with failures and transition info."""
    results = [check_health(pid, url) for pid, url in HEALTH_URLS.items()]
    failures = [r for r in results if not r["ok"]]

    current_status = "unhealthy" if failures else "healthy"
    previous_status = _get_last_status()
    _set_last_status(current_status)

    # Determine if this is a state transition
    is_transition = previous_status is not None and previous_status != current_status
    # Also notify if previous_status is None and current is unhealthy (first run)
    is_new_failure = previous_status is None and current_status == "unhealthy"

    return {
        "total": len(results),
        "healthy": len(results) - len(failures),
        "failures": failures,
        "previous_status": previous_status,
        "current_status": current_status,
        "should_notify": is_transition or is_new_failure,
    }
