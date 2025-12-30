"""Celery tasks for Explorer scheduled scans.

Tasks:
- scan_all_projects: Run Explorer scan for all registered projects
"""

from __future__ import annotations

import time
from typing import Any

from celery import shared_task  # type: ignore[import-untyped]

from ..logging_config import get_logger
from ..services import explorer
from ..storage.connection import get_connection

logger = get_logger(__name__)

# Rate limit delay between projects (seconds)
INTER_PROJECT_DELAY = 5


@shared_task(name="summitflow.scan_all_projects")  # type: ignore[untyped-decorator]
def scan_all_projects(
    project_id: str | None = None,
    entry_type: str | None = None,
    dry_run: bool = False,
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
                result = _scan_project(proj_id, entry_type)
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


def _scan_project(project_id: str, entry_type: str | None = None) -> list[dict[str, Any]]:
    """Scan a single project and return results.

    Args:
        project_id: Project to scan
        entry_type: Optional specific type (None = all types)

    Returns:
        List of scan results for each entry type
    """
    from ..services.explorer.types import list_registered_types

    types_to_scan = [entry_type] if entry_type else list_registered_types()
    results = []

    for t in types_to_scan:
        result = explorer.scan(project_id, t)
        results.append(
            {
                "entry_type": result.entry_type,
                "entries_found": result.entries_found,
                "entries_saved": result.entries_saved,
                "duration_ms": result.duration_ms,
                "success": result.success,
                "error": result.error,
            }
        )

    return results
