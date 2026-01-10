"""Celery task for periodic worktree cleanup.

Runs as a scheduled task to remove old worktrees and maintain hygiene.
"""

from __future__ import annotations

from typing import Any

from app.celery_app import celery_app
from app.logging_config import get_logger
from app.storage.projects import list_projects

logger = get_logger(__name__)


# Default cleanup configuration
DEFAULT_MAX_AGE_DAYS = 30
DEFAULT_WARNING_THRESHOLD = 10
DEFAULT_CRITICAL_THRESHOLD = 25


@celery_app.task(name="summitflow.cleanup_worktrees")  # type: ignore[untyped-decorator]
def cleanup_worktrees(
    project_id: str | None = None,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Clean up old worktrees.

    Args:
        project_id: Specific project to clean (None = all projects)
        max_age_days: Maximum age before cleanup (default 30)
        dry_run: Preview mode - don't actually delete

    Returns:
        Dict with cleanup results per project
    """

    from pathlib import Path

    from app.services.worktree_manager import WorktreeManager
    from app.storage.projects import get_project_root_path

    results: dict[str, Any] = {"projects": {}, "total_removed": 0}

    try:
        if project_id:
            # Single project cleanup
            root_path = get_project_root_path(project_id)
            if root_path:
                manager = WorktreeManager(Path(root_path))
                cleanup_result = manager.cleanup_old_worktrees(
                    max_age_days=max_age_days, dry_run=dry_run
                )
                results["projects"][project_id] = cleanup_result
                key = "would_remove" if dry_run else "removed"
                results["total_removed"] = len(cleanup_result.get(key, []))
        else:
            # All projects cleanup
            projects = list_projects()
            for project in projects:
                pid = project.get("project_id")
                root_path = project.get("root_path")
                if pid and root_path:
                    try:
                        manager = WorktreeManager(Path(root_path))
                        cleanup_result = manager.cleanup_old_worktrees(
                            max_age_days=max_age_days, dry_run=dry_run
                        )
                        results["projects"][pid] = cleanup_result
                        key = "would_remove" if dry_run else "removed"
                        results["total_removed"] += len(cleanup_result.get(key, []))
                    except Exception as e:
                        logger.warning("cleanup_project_failed", project=pid, error=str(e))
                        results["projects"][pid] = {"error": str(e)}

        results["dry_run"] = dry_run
        results["max_age_days"] = max_age_days

        logger.info(
            "worktree_cleanup_complete",
            total_removed=results["total_removed"],
            dry_run=dry_run,
        )

    except Exception as e:
        logger.error("worktree_cleanup_error", error=str(e))
        results["error"] = str(e)

    return results


@celery_app.task(name="summitflow.check_worktree_thresholds")  # type: ignore[untyped-decorator]
def check_worktree_thresholds(
    warning_threshold: int = DEFAULT_WARNING_THRESHOLD,
    critical_threshold: int = DEFAULT_CRITICAL_THRESHOLD,
) -> dict[str, Any]:
    """Check worktree counts against thresholds and alert if exceeded.

    Args:
        warning_threshold: Count to trigger warning
        critical_threshold: Count to trigger critical alert

    Returns:
        Dict with threshold check results per project
    """
    from pathlib import Path

    from app.services.worktree_manager import WorktreeManager

    results: dict[str, Any] = {"projects": {}, "alerts": []}

    try:
        projects = list_projects()
        for project in projects:
            pid = project.get("project_id")
            root_path = project.get("root_path")
            if pid and root_path:
                try:
                    manager = WorktreeManager(Path(root_path))
                    check = manager.get_worktree_count_warning(
                        warning_threshold=warning_threshold,
                        critical_threshold=critical_threshold,
                    )
                    results["projects"][pid] = check

                    if check.get("level"):
                        results["alerts"].append(
                            {
                                "project_id": pid,
                                "level": check["level"],
                                "message": check["message"],
                            }
                        )
                except Exception as e:
                    logger.warning("threshold_check_failed", project=pid, error=str(e))

        if results["alerts"]:
            logger.warning("worktree_threshold_alerts", alerts=results["alerts"])

    except Exception as e:
        logger.error("threshold_check_error", error=str(e))
        results["error"] = str(e)

    return results
