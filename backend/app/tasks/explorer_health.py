"""Explorer health check utilities for page monitoring."""

from __future__ import annotations

import json
import subprocess
import time
from typing import Any

from ..logging_config import get_logger
from ..storage import explorer_entries
from ..storage.connection import get_connection

logger = get_logger(__name__)

# Rate limit delay between health checks (seconds)
HEALTH_CHECK_DELAY = 1


def run_page_health_checks(project_id: str) -> dict[str, Any]:
    """Run health checks on all page entries for a project.

    Uses ba check to verify each page:
    - HTTP response status
    - Console errors
    - Response time

    Args:
        project_id: Project to check

    Returns:
        Summary dict with check results
    """

    logger.info("page_health_checks_started", project_id=project_id)

    try:
        # Get project base URL
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT base_url, frontend_port FROM projects WHERE id = %s",
                (project_id,),
            )
            row = cur.fetchone()
            if not row:
                return {"status": "error", "error": f"Project not found: {project_id}"}
            base_url, port = row

        # Get all page entries
        pages = explorer_entries.get_pages_for_health_check(project_id)
        if not pages:
            return {"status": "success", "message": "No pages to check", "checked": 0}

        # Build base URL with port
        if base_url and "localhost" in base_url:
            check_base = f"http://localhost:{port or 3001}"
        else:
            check_base = base_url or f"http://localhost:{port or 3001}"

        checked = 0
        errors = 0
        results: list[dict[str, Any]] = []

        for i, page in enumerate(pages):
            # Rate limit between checks (except first)
            if i > 0:
                time.sleep(HEALTH_CHECK_DELAY)

            path = page["path"]
            url = f"{check_base}{path}"

            try:
                result = run_ba_check(url)
                health_status = "healthy" if result.get("pass") else "error"
                console_errors = result.get("checks", {}).get("consoleErrors", {})

                health_data = {
                    "http_status": 200 if result.get("pass") else 500,
                    "console_error_count": console_errors.get("count", 0),
                    "console_errors": console_errors.get("messages", [])[:5],
                    "response_time_ms": result.get("durationMs", 0),
                    "last_health_check": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                }

                explorer_entries.update_health_check(page["id"], health_status, health_data)

                results.append(
                    {
                        "path": path,
                        "status": health_status,
                        "console_errors": console_errors.get("count", 0),
                    }
                )
                checked += 1

            except Exception as e:
                errors += 1
                logger.error("page_health_check_failed", path=path, error=str(e))
                results.append(
                    {
                        "path": path,
                        "status": "error",
                        "error": str(e),
                    }
                )

        logger.info(
            "page_health_checks_complete",
            project_id=project_id,
            checked=checked,
            errors=errors,
        )

        return {
            "status": "success" if errors == 0 else "partial",
            "project_id": project_id,
            "checked": checked,
            "errors": errors,
            "results": results,
        }

    except Exception as e:
        logger.error("page_health_checks_failed", project_id=project_id, error=str(e))
        return {"status": "error", "project_id": project_id, "error": str(e)}


def run_ba_check(url: str, timeout: int = 30) -> dict[str, Any]:
    """Run ba check command and parse JSON output.

    Args:
        url: URL to check
        timeout: Command timeout in seconds

    Returns:
        Parsed JSON result from ba check
    """
    result = subprocess.run(
        ["ba", "check", url, "--no-errors"],
        capture_output=True,
        text=True,
        timeout=timeout,
    )

    if result.returncode != 0 and not result.stdout:
        raise RuntimeError(f"ba check failed: {result.stderr}")

    data: dict[str, Any] = json.loads(result.stdout)
    return data
