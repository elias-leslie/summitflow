"""Celery tasks for self-healing monitoring.

Scheduled tasks that monitor systemd journals for runtime errors
and create bug tasks for detected issues.
"""

from __future__ import annotations

from celery import shared_task

from ..logging_config import get_logger
from ..services.self_healing.monitor import (
    SystemdMonitor,
    create_error_task,
)

logger = get_logger(__name__)

# Maximum tasks to create per monitoring run
MAX_TASKS_PER_RUN = 10


@shared_task(name="summitflow.monitor_systemd_errors")  # type: ignore[untyped-decorator]
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
