"""Celery tasks for self-healing monitoring and orchestration.

Scheduled tasks that:
1. Monitor systemd journals for runtime errors and create bug tasks
2. Orchestrate automated fix triggering for quality gate failures
"""

from __future__ import annotations

from typing import Any

from celery import shared_task

from ..logging_config import get_logger
from ..services.self_healing.browser_monitor import (
    BrowserErrorMonitor,
    create_browser_error_task,
)
from ..services.self_healing.monitor import (
    SystemdMonitor,
    create_error_task,
)
from ..storage.connection import get_connection

logger = get_logger(__name__)

# Maximum tasks to create per monitoring run
MAX_TASKS_PER_RUN = 10


@shared_task(name="summitflow.monitor_browser_errors")
def monitor_browser_errors(
    project_id: str = "summitflow",
    max_tasks: int = MAX_TASKS_PER_RUN,
) -> dict[str, int]:
    """Monitor browser console errors and create bug tasks.

    Scheduled task that runs after explorer health checks to detect
    console errors on pages and create bug tasks for investigation.

    Args:
        project_id: Project ID for task creation
        max_tasks: Maximum number of tasks to create per run

    Returns:
        Dict with counts: created, skipped, errors
    """
    logger.info(
        "starting_browser_error_monitoring",
        project_id=project_id,
        max_tasks=max_tasks,
    )

    results = {"created": 0, "skipped": 0, "errors": 0}

    try:
        monitor = BrowserErrorMonitor(project_id)
        new_errors = monitor.get_new_errors()

        if not new_errors:
            logger.debug("no_new_browser_errors_detected")
            return results

        logger.info("new_browser_errors_found", count=len(new_errors))

        # Rate limit: process only up to max_tasks
        for error in new_errors[:max_tasks]:
            try:
                task = create_browser_error_task(project_id, error)
                if task:
                    results["created"] += 1
                    logger.info(
                        "created_browser_error_task",
                        task_id=task["id"],
                        page_path=error.page_path,
                    )
                else:
                    results["skipped"] += 1
            except Exception as e:
                logger.error(
                    "browser_task_creation_failed",
                    error_hash=error.error_hash,
                    error=str(e),
                )
                results["errors"] += 1

        # Log if we hit the rate limit
        if len(new_errors) > max_tasks:
            logger.warning(
                "browser_monitoring_rate_limited",
                total_errors=len(new_errors),
                processed=max_tasks,
                skipped=len(new_errors) - max_tasks,
            )

    except Exception as e:
        logger.error("browser_monitoring_failed", error=str(e))
        results["errors"] += 1

    logger.info(
        "browser_monitoring_complete",
        **results,
    )

    return results


@shared_task(name="summitflow.monitor_systemd_errors")
def monitor_systemd_errors(
    project_id: str = "summitflow",
    since: str = "5 minutes ago",
    max_tasks: int = MAX_TASKS_PER_RUN,
) -> dict[str, int]:
    """Monitor systemd journal for errors and create bug tasks.

    Scheduled task that runs periodically to detect runtime errors
    in SummitFlow services and create bug tasks for investigation.

    Args:
        project_id: Project ID for task creation
        since: Time window for journal queries
        max_tasks: Maximum number of tasks to create per run

    Returns:
        Dict with counts: created, skipped, errors
    """
    logger.info(
        "starting_systemd_monitoring",
        project_id=project_id,
        since=since,
        max_tasks=max_tasks,
    )

    results = {"created": 0, "skipped": 0, "errors": 0}

    try:
        monitor = SystemdMonitor(since=since)
        new_errors = monitor.get_new_errors()

        if not new_errors:
            logger.debug("no_new_errors_detected")
            return results

        logger.info("new_errors_found", count=len(new_errors))

        # Rate limit: process only up to max_tasks
        for error in new_errors[:max_tasks]:
            try:
                task = create_error_task(project_id, error)
                if task:
                    results["created"] += 1
                    logger.info(
                        "created_task",
                        task_id=task["id"],
                        unit=error.unit,
                    )
                else:
                    results["skipped"] += 1
            except Exception as e:
                logger.error(
                    "task_creation_failed",
                    error_hash=error.error_hash,
                    error=str(e),
                )
                results["errors"] += 1

        # Log if we hit the rate limit
        if len(new_errors) > max_tasks:
            logger.warning(
                "rate_limited",
                total_errors=len(new_errors),
                processed=max_tasks,
                skipped=len(new_errors) - max_tasks,
            )

    except Exception as e:
        logger.error("monitoring_failed", error=str(e))
        results["errors"] += 1

    logger.info(
        "monitoring_complete",
        **results,
    )

    return results


# Default configuration for self-healing orchestration
DEFAULT_MAX_ERRORS = 20
DEFAULT_ENABLED = True


@shared_task(name="summitflow.orchestrate_self_healing")
def orchestrate_self_healing(
    max_errors: int = DEFAULT_MAX_ERRORS,
    enabled: bool = DEFAULT_ENABLED,
) -> dict[str, Any]:
    """Orchestrate automated fix triggering for quality gate failures.

    Scheduled task that runs periodically to:
    1. Poll all projects for unfixed quality gate errors
    2. Trigger fix agents with 3-2-1 escalation
    3. Track and report results

    Args:
        max_errors: Maximum number of errors to process per run
        enabled: Whether self-healing is enabled (for easy disable via config)

    Returns:
        Dict with orchestration results:
        - enabled: bool
        - projects_processed: int
        - total_fixed: int
        - total_failed: int
        - total_escalated: int
        - by_check_type: dict
        - by_project: dict
    """
    if not enabled:
        logger.info("self_healing_disabled")
        return {"enabled": False, "skipped": True}

    logger.info(
        "starting_self_healing_orchestration",
        max_errors=max_errors,
    )

    # Lazy import to avoid circular dependency at module load
    from ..services.self_healing.orchestrator import SelfHealingOrchestrator

    try:
        with get_connection() as conn:
            orchestrator = SelfHealingOrchestrator(conn, max_errors_per_run=max_errors)

            # Check if there's work to do
            health = orchestrator.get_health_summary()
            if not health["should_run"]:
                logger.info("no_unfixed_errors")
                return {
                    "enabled": True,
                    "projects_processed": 0,
                    "total_fixed": 0,
                    "total_failed": 0,
                    "total_escalated": 0,
                    "message": "No unfixed errors to process",
                }

            logger.info(
                "unfixed_errors_found",
                total=health["total_unfixed"],
                projects=health["projects_needing_fixes"],
            )

            # Run the orchestration
            results = orchestrator.poll_and_fix()
            conn.commit()

            logger.info(
                "self_healing_complete",
                projects=results["projects_processed"],
                fixed=results["total_fixed"],
                failed=results["total_failed"],
                escalated=results["total_escalated"],
            )

            return {
                "enabled": True,
                **results,
            }

    except Exception as e:
        logger.error("self_healing_orchestration_failed", error=str(e))
        return {
            "enabled": True,
            "error": str(e),
            "projects_processed": 0,
            "total_fixed": 0,
            "total_failed": 0,
            "total_escalated": 0,
        }
