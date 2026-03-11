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

HEALTH_CHECK_DELAY = 1
STATUS_HEALTHY = "healthy"
STATUS_ERROR = "error"
STATUS_SUCCESS = "success"
STATUS_PARTIAL = "partial"
BA_CMD = "ba"
BA_SUBCMD = "check"
BA_FLAG_NO_ERRORS = "--no-errors"
TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
DEFAULT_LOCAL_PORT = 3001
LOCALHOST_HOSTNAME = "localhost"


def _get_project_info(project_id: str) -> tuple[str | None, int | None] | None:
    """Return (base_url, port) for a project, or None if not found."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT base_url, frontend_port FROM projects WHERE id = %s",
            (project_id,),
        )
        row = cur.fetchone()
        return None if not row else (row[0], row[1])


def _build_check_base(base_url: str | None, port: int | None) -> str:
    """Construct the base URL to use for health checks."""
    effective_port = port or DEFAULT_LOCAL_PORT
    if base_url and LOCALHOST_HOSTNAME not in base_url:
        return base_url
    return f"http://{LOCALHOST_HOSTNAME}:{effective_port}"


def _now_utc() -> str:
    """Return current UTC time as ISO 8601 string."""
    return time.strftime(TIMESTAMP_FORMAT, time.gmtime())


def _check_single_page(page: dict[str, Any], check_base: str) -> dict[str, Any]:
    """Run a health check on a single page and persist the result."""
    path = page["path"]
    page_url = page.get("metadata", {}).get("url")
    target_url = page_url if isinstance(page_url, str) and page_url else f"{check_base}{path}"
    result = run_ba_check(target_url)
    passed = result.get("pass")
    health_status = STATUS_HEALTHY if passed else STATUS_ERROR
    console_errors = result.get("checks", {}).get("consoleErrors", {})
    explorer_entries.update_health_check(
        page["id"],
        health_status,
        {
            "http_status": 200 if passed else 500,
            "console_error_count": console_errors.get("count", 0),
            "console_errors": console_errors.get("messages", [])[:5],
            "response_time_ms": result.get("durationMs", 0),
            "last_health_check": _now_utc(),
        },
    )
    return {"path": path, "status": health_status, "console_errors": console_errors.get("count", 0)}


def _process_pages(
    pages: list[dict[str, Any]], check_base: str
) -> tuple[int, int, list[dict[str, Any]]]:
    """Iterate pages, run health checks, collect results."""
    checked = 0
    errors = 0
    results: list[dict[str, Any]] = []
    for i, page in enumerate(pages):
        if i > 0:
            time.sleep(HEALTH_CHECK_DELAY)
        path = page["path"]
        try:
            results.append(_check_single_page(page, check_base))
            checked += 1
        except Exception as e:
            errors += 1
            logger.error("page_health_check_failed", path=path, error=str(e))
            results.append({"path": path, "status": STATUS_ERROR, "error": str(e)})
    return checked, errors, results


def run_page_health_checks(project_id: str) -> dict[str, Any]:
    """Run health checks on all page entries for a project."""
    logger.info("page_health_checks_started", project_id=project_id)
    try:
        project_info = _get_project_info(project_id)
        if project_info is None:
            return {"status": STATUS_ERROR, "error": f"Project not found: {project_id}"}
        pages = explorer_entries.get_pages_for_health_check(project_id)
        if not pages:
            return {"status": STATUS_SUCCESS, "message": "No pages to check", "checked": 0}
        checked, errors, results = _process_pages(pages, _build_check_base(*project_info))
        logger.info("page_health_checks_complete", project_id=project_id, checked=checked, errors=errors)
        return {
            "status": STATUS_SUCCESS if errors == 0 else STATUS_PARTIAL,
            "project_id": project_id,
            "checked": checked,
            "errors": errors,
            "results": results,
        }
    except Exception as e:
        logger.error("page_health_checks_failed", project_id=project_id, error=str(e))
        return {"status": STATUS_ERROR, "project_id": project_id, "error": str(e)}


def run_ba_check(url: str, timeout: int = 30) -> dict[str, Any]:
    """Run ba check command and parse JSON output."""
    result = subprocess.run(
        [BA_CMD, BA_SUBCMD, url, BA_FLAG_NO_ERRORS],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0 and not result.stdout:
        raise RuntimeError(f"ba check failed: {result.stderr}")
    return json.loads(result.stdout)
