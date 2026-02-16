"""Production smoke tests via CF Access tunnel.

Hits health endpoints through cf-curl and reports failures.
Called by the prod-smoke-test cron workflow every 15 minutes.
"""

from __future__ import annotations

import logging
import subprocess
from typing import Any

logger = logging.getLogger(__name__)

# Production health endpoints (via Cloudflare Access tunnel)
PROD_HEALTH_URLS: dict[str, str] = {
    "summitflow": "https://devapi.summitflow.dev/health",
    "agent-hub": "https://agentapi.summitflow.dev/health",
    "portfolio-ai": "https://portapi.summitflow.dev/health",
    "terminal": "https://terminalapi.summitflow.dev/health",
}


def check_health(project_id: str, url: str) -> dict[str, Any]:
    """Check a single health endpoint via cf-curl."""
    try:
        result = subprocess.run(
            ["cf-curl", "-sf", url],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return {
            "project": project_id,
            "url": url,
            "ok": result.returncode == 0,
            "status": "healthy" if result.returncode == 0 else "unhealthy",
        }
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        return {
            "project": project_id,
            "url": url,
            "ok": False,
            "status": f"error: {e}",
        }


def run_all_smoke_tests() -> dict[str, Any]:
    """Run all production health checks. Returns summary with failures list."""
    results = [check_health(pid, url) for pid, url in PROD_HEALTH_URLS.items()]
    failures = [r for r in results if not r["ok"]]

    return {
        "total": len(results),
        "healthy": len(results) - len(failures),
        "failures": failures,
    }
