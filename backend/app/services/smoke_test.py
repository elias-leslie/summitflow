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

from ..config import SUMMITFLOW_BACKEND_PORT
from ..logging_config import get_logger
from . import tether
from .redis_pool import get_redis

logger = get_logger(__name__)

_REDIS_KEY = "smoke_test:last_status"
_REDIS_TTL = 3600  # 1 hour — re-notify if still failing after TTL expires

# Health endpoints — only check services whose URL is explicitly configured.
# SummitFlow self-health is always checked; any other project is checked when
# <PROJECT_ID>_HEALTH_URL is set (e.g. AGENT_HUB_HEALTH_URL -> agent-hub), so
# partial profiles skip services they don't include.
def _build_health_urls() -> dict[str, str]:
    urls: dict[str, str] = {
        "summitflow": os.getenv(
            "SUMMITFLOW_HEALTH_URL",
            f"http://localhost:{SUMMITFLOW_BACKEND_PORT}/health",
        ),
    }
    for key, url in sorted(os.environ.items()):
        project_id = key.removesuffix("_HEALTH_URL").lower().replace("_", "-")
        if key.endswith("_HEALTH_URL") and url and project_id and project_id not in urls:
            urls[project_id] = url
    return urls


HEALTH_URLS: dict[str, str] = _build_health_urls()


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


def check_tether_health() -> dict[str, Any] | None:
    """Tether's socket health; None (not checked) when Tether is not installed/running.

    Tether has no TCP port. A missing socket is not a failure, so hosts without
    Tether (or before its cutover) stay healthy; a socket that does not answer is.
    """
    if not tether.socket_present():
        return None
    data = tether.health(timeout=5)
    ok = data is not None
    return {
        "project": "tether",
        "url": f"unix:{tether.socket_path()}/v1/health",
        "ok": ok,
        "status": "healthy" if ok else "error: socket present but /v1/health did not answer ok",
    }


def _get_last_status() -> str | None:
    """Read last known smoke test status from Redis."""
    try:
        raw = get_redis().get(_REDIS_KEY)
        if isinstance(raw, bytes):
            data = json.loads(raw.decode("utf-8"))
            return data.get("status")
        if isinstance(raw, str):
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
    if (tether_result := check_tether_health()) is not None:
        results.append(tether_result)
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
