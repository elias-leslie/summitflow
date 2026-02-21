"""Background tasks for Explorer scheduled scans.

Tasks:
- scan_all_projects: Run Explorer scan for all registered projects
- run_page_health_checks: Run ba check on all page entries
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from ..logging_config import get_logger
from ..storage.connection import get_connection
from .explorer_health import run_page_health_checks as _run_page_health_checks
from .explorer_resolution import check_and_close_resolved_issues
from .explorer_scan import scan_project

logger = get_logger(__name__)

# Rate limit delay between projects (seconds)
INTER_PROJECT_DELAY = 5


def _fetch_projects(project_id: str | None) -> list[tuple]:
    """Fetch projects from the database."""
    with get_connection() as conn, conn.cursor() as cur:
        if project_id:
            cur.execute(
                "SELECT id, name, root_path FROM projects WHERE id = %s",
                (project_id,),
            )
        else:
            cur.execute("SELECT id, name, root_path FROM projects ORDER BY created_at")
        return cur.fetchall()


def _make_dry_run_detail(proj_id: str, proj_name: str) -> dict[str, Any]:
    """Build a dry-run detail entry and log it."""
    logger.info("would_scan", project_id=proj_id, project_name=proj_name)
    return {"project_id": proj_id, "project_name": proj_name, "status": "would_scan"}


def _dispatch_post_scan_tasks(dispatch: Callable[[str, str, str], None], proj_id: str) -> None:
    """Trigger post-scan downstream tasks via the dispatch callback."""
    logger.info("triggering_post_scan_tasks", project_id=proj_id)
    dispatch("generate_tasks", "", proj_id)
    # DISABLED: Schema tasks created 210+ pending debt tasks with 172 duplicates,
    # 0 ever completed. Violations remain visible on Explorer health dashboard. — 2026-02-20
    # dispatch("schema_tasks", "", proj_id)
    dispatch("architecture_tasks", "", proj_id)
    dispatch("check_resolved", "", proj_id)


def _scan_single_project(
    proj_id: str,
    proj_name: str,
    entry_type: str | None,
    dispatch: Callable[[str, str, str], None] | None,
) -> tuple[dict[str, Any], bool]:
    """Scan one project; return (detail_dict, success_flag)."""
    try:
        result = scan_project(proj_id, entry_type)
        logger.info("project_scanned", project_id=proj_id, results_count=len(result))
        if dispatch:
            _dispatch_post_scan_tasks(dispatch, proj_id)
        detail = {
            "project_id": proj_id,
            "project_name": proj_name,
            "status": "success",
            "results": result,
        }
        return detail, True
    except Exception as e:
        logger.error("project_scan_failed", project_id=proj_id, error=str(e))
        detail = {
            "project_id": proj_id,
            "project_name": proj_name,
            "status": "error",
            "error": str(e),
        }
        return detail, False


def _process_projects(
    projects: list[tuple],
    entry_type: str | None,
    dry_run: bool,
    dispatch: Callable[[str, str, str], None] | None,
) -> tuple[int, int, list[dict[str, Any]]]:
    """Iterate projects and return (scanned, errors, details)."""
    scanned = 0
    errors = 0
    details: list[dict[str, Any]] = []

    for i, (proj_id, proj_name, _root_path) in enumerate(projects):
        if i > 0 and not dry_run:
            time.sleep(INTER_PROJECT_DELAY)

        if dry_run:
            details.append(_make_dry_run_detail(proj_id, proj_name))
            scanned += 1
            continue

        detail, success = _scan_single_project(proj_id, proj_name, entry_type, dispatch)
        details.append(detail)
        if success:
            scanned += 1
        else:
            errors += 1

    return scanned, errors, details


def scan_all_projects(
    project_id: str | None = None,
    entry_type: str | None = None,
    dry_run: bool = False,
    dispatch: Callable[[str, str, str], None] | None = None,
) -> dict[str, Any]:
    """Run Explorer scan for all registered projects.

    Scans all entry types (file, table, task, endpoint, page) for each project.
    Rate limited between projects to avoid overwhelming the system.

    Args:
        project_id: Optional specific project to scan (None = all projects)
        entry_type: Optional specific type to scan (None = all types)
        dry_run: If True, only report what would be scanned

    Returns:
        Summary dict with scanned projects and results
    """
    logger.info(
        "scan_all_projects_started",
        project_id=project_id or "all",
        entry_type=entry_type or "all",
        dry_run=dry_run,
    )

    try:
        projects = _fetch_projects(project_id)

        if not projects:
            logger.info("no_projects_found")
            return {"status": "success", "message": "No projects to scan", "scanned": 0}

        scanned, errors, details = _process_projects(projects, entry_type, dry_run, dispatch)

        logger.info("scan_all_projects_complete", scanned=scanned, errors=errors)
        return {
            "status": "success" if errors == 0 else "partial",
            "dry_run": dry_run,
            "scanned": scanned,
            "errors": errors,
            "details": details,
        }

    except Exception as e:
        logger.error("scan_all_projects_failed", error=str(e))
        return {"status": "error", "error": str(e)}


def check_resolved_issues(project_id: str, scan_id: int | None = None) -> dict[str, Any]:
    """Check for resolved issues after a scan.

    Args:
        project_id: Project that was scanned
        scan_id: Optional scan ID for tracking

    Returns:
        Summary dict with closed task count
    """
    try:
        closed_count = check_and_close_resolved_issues(project_id, scan_id)
        return {
            "status": "success",
            "project_id": project_id,
            "tasks_closed": closed_count,
        }
    except Exception as e:
        logger.error(
            "check_resolved_issues_failed",
            project_id=project_id,
            error=str(e),
        )
        return {
            "status": "error",
            "project_id": project_id,
            "error": str(e),
        }


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
    return _run_page_health_checks(project_id)
