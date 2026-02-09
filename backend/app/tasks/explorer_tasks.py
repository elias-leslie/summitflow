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
        # Get projects to scan
        with get_connection() as conn, conn.cursor() as cur:
            if project_id:
                cur.execute(
                    "SELECT id, name, root_path FROM projects WHERE id = %s",
                    (project_id,),
                )
            else:
                cur.execute("SELECT id, name, root_path FROM projects ORDER BY created_at")
            projects = cur.fetchall()

        if not projects:
            logger.info("no_projects_found")
            return {"status": "success", "message": "No projects to scan", "scanned": 0}

        scanned = 0
        errors = 0
        details: list[dict[str, Any]] = []

        for i, (proj_id, proj_name, _root_path) in enumerate(projects):
            # Rate limit between projects (except first)
            if i > 0 and not dry_run:
                time.sleep(INTER_PROJECT_DELAY)

            if dry_run:
                logger.info("would_scan", project_id=proj_id, project_name=proj_name)
                details.append(
                    {
                        "project_id": proj_id,
                        "project_name": proj_name,
                        "status": "would_scan",
                    }
                )
                scanned += 1
                continue

            try:
                result = scan_project(proj_id, entry_type)
                details.append(
                    {
                        "project_id": proj_id,
                        "project_name": proj_name,
                        "status": "success",
                        "results": result,
                    }
                )
                scanned += 1
                logger.info(
                    "project_scanned",
                    project_id=proj_id,
                    results_count=len(result),
                )

                # Trigger post-scan tasks via dispatch callback
                if dispatch:
                    logger.info(
                        "triggering_post_scan_tasks",
                        project_id=proj_id,
                    )
                    dispatch("generate_tasks", "", proj_id)
                    dispatch("schema_tasks", "", proj_id)
                    dispatch("architecture_tasks", "", proj_id)
                    dispatch("check_resolved", "", proj_id)
            except Exception as e:
                errors += 1
                details.append(
                    {
                        "project_id": proj_id,
                        "project_name": proj_name,
                        "status": "error",
                        "error": str(e),
                    }
                )
                logger.error(
                    "project_scan_failed",
                    project_id=proj_id,
                    error=str(e),
                )

        logger.info(
            "scan_all_projects_complete",
            scanned=scanned,
            errors=errors,
        )

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
