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
from ..services.task_issue_mapper import QAIssue, close_task_for_issue
from ..storage import qa_issues as qa_storage
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

                # Trigger post-scan tasks
                # Use send_task to avoid circular import with autonomous.py
                from celery import current_app

                logger.info(
                    "triggering_post_scan_tasks",
                    project_id=proj_id,
                )
                current_app.send_task("summitflow.generate_tasks_from_scan", args=[proj_id])
                current_app.send_task("summitflow.generate_bug_tasks", args=[proj_id])
                # Check for resolved issues and auto-close linked tasks
                current_app.send_task("summitflow.check_resolved_issues", args=[proj_id])
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


def _check_and_close_resolved_issues(project_id: str, scan_id: int | None = None) -> int:
    """Check for resolved issues and auto-close linked tasks.

    After a scan, check which open issues are no longer detected.
    For issues linked to SummitFlow tasks, auto-close the tasks.

    This implements the self-healing loop:
    1. Scan detects issue -> create task
    2. User/agent fixes issue
    3. Next scan doesn't detect issue -> mark resolved, close task

    Args:
        project_id: Project that was scanned
        scan_id: Optional scan ID for tracking

    Returns:
        Number of tasks auto-closed
    """
    closed_count = 0

    # Get all open issues linked to tasks
    linked_issues = qa_storage.get_issues_linked_to_tasks(project_id)
    if not linked_issues:
        return 0

    logger.info(
        "checking_resolved_issues",
        project_id=project_id,
        linked_count=len(linked_issues),
    )

    # Check each linked issue to see if it's still valid
    for issue in linked_issues:
        if not _issue_still_exists(project_id, issue):
            # Issue is resolved - mark it and close the task
            qa_storage.mark_issue_resolved(
                issue["id"],
                scan_id=scan_id,
                reason="Issue no longer detected in scan",
            )

            # Close the linked task
            qa_issue = QAIssue(
                id=issue["id"],
                project_id=issue["project_id"],
                issue_type=issue["issue_type"],
                severity=issue["severity"],
                title=issue["title"],
                description=issue.get("description"),
                file_path=issue.get("file_path"),
                st_task_id=issue["st_task_id"],
            )
            if close_task_for_issue(qa_issue):
                closed_count += 1
                logger.info(
                    "auto_closed_task",
                    issue_id=issue["id"],
                    task_id=issue["st_task_id"],
                )

    if closed_count > 0:
        logger.info(
            "self_healing_complete",
            project_id=project_id,
            tasks_closed=closed_count,
        )

    return closed_count


def _issue_still_exists(project_id: str, issue: dict[str, Any]) -> bool:
    """Check if a QA issue still exists in the codebase.

    For file-based issues (complexity, stale_file), check if the
    file still has the issue in the explorer entries.

    For error issues, check if the error observation still exists
    and hasn't been marked as resolved.

    Args:
        project_id: Project ID
        issue: Issue dict from qa_issues table

    Returns:
        True if issue still exists, False if resolved
    """
    file_path = issue.get("file_path")
    issue_type = issue.get("issue_type")
    issue_metadata = issue.get("metadata") or {}

    # Handle error issues separately (may not have file_path)
    if issue_type == "error":
        return _error_issue_still_exists(project_id, issue, issue_metadata)

    if not file_path:
        # Non-file issues without special handling - assume still exists
        return True

    # Get the explorer entry for this file
    entry = explorer.get_entry(project_id, "file", file_path)
    if not entry:
        # File was deleted - issue is resolved
        return False

    # Check issue type-specific criteria
    if issue_type == "complexity":
        # Check if complexity is still above threshold
        # Threshold matches task generation: tier 1 starts at complexity > 10
        metadata = entry.get("metadata", {})
        complexity = metadata.get("complexity_score", 0)
        return bool(complexity >= 10)

    elif issue_type == "stale_file":
        # Check if file is still stale (no commits in 180+ days)
        metadata = entry.get("metadata", {})
        stale_status = metadata.get("stale_status")
        return bool(stale_status in ("stale", "orphan"))

    elif issue_type == "bloat":
        # Check if file is still bloated
        metadata = entry.get("metadata", {})
        bloat_level = metadata.get("bloat_level")
        return bool(bloat_level in ("warning", "critical"))

    # Default: assume issue still exists
    return True


def _error_issue_still_exists(
    project_id: str,
    issue: dict[str, Any],
    issue_metadata: dict[str, Any],
) -> bool:
    """Check if an error issue still exists.

    Error issues are resolved when:
    1. The source observation was marked as resolved
    2. No recent error observations match the same title
    3. The affected files no longer have type/lint errors

    Args:
        project_id: Project ID
        issue: Issue dict from qa_issues table
        issue_metadata: Parsed metadata from issue

    Returns:
        True if error still exists, False if resolved
    """
    from ..storage.memory import query_observations

    error_title = issue.get("title", "")
    if not error_title:
        return True  # Can't verify without title

    # Check if any recent error observations match this title
    # If no recent errors, the issue is resolved
    recent_errors = query_observations(
        project_id=project_id,
        observation_type="error",
        min_confidence=0.7,
        days=3,  # Look back 3 days for recent occurrences
        limit=50,
    )

    # Check if any observation matches this error title
    for obs in recent_errors:
        obs_title = obs.get("title", "")
        # Fuzzy match: if titles are substantially similar, error still exists
        if error_title.lower() in obs_title.lower() or obs_title.lower() in error_title.lower():
            return True

    # No recent matching errors - issue is resolved
    logger.info(
        "error_issue_resolved",
        issue_id=issue.get("id"),
        title=error_title[:60],
        reason="no_recent_matching_errors",
    )
    return False


@shared_task(name="summitflow.check_resolved_issues")  # type: ignore[untyped-decorator]
def check_resolved_issues(project_id: str, scan_id: int | None = None) -> dict[str, Any]:
    """Celery task to check for resolved issues after a scan.

    Args:
        project_id: Project that was scanned
        scan_id: Optional scan ID for tracking

    Returns:
        Summary dict with closed task count
    """
    try:
        closed_count = _check_and_close_resolved_issues(project_id, scan_id)
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
