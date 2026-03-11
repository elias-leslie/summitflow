"""Daily maintenance orchestration for retention and stale-record recovery."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..logging_config import get_logger
from ..storage import backups as backup_store
from ..storage import notifications as notification_store
from ..storage import quality_check_results as qcr_store
from ..storage import scan_history
from .autonomous.cleanup_operations import cleanup_stale_tasks

logger = get_logger(__name__)


def _run_step(name: str, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Run a maintenance step without aborting the whole sweep on one failure."""
    try:
        result = fn(*args, **kwargs)
        logger.info("daily_maintenance_step_completed", step=name)
        return result
    except Exception as exc:
        logger.exception("daily_maintenance_step_failed", step=name)
        return {"error": str(exc)}


def run_daily_maintenance(max_age_days: int = 30) -> dict[str, Any]:
    """Run the daily retention and stale-state cleanup workflow."""
    logger.info("daily_maintenance_started", max_age_days=max_age_days)

    task_cleanup = _run_step("stale_tasks", cleanup_stale_tasks, max_age_days)
    stale_scan_failures = _run_step(
        "stale_running_scans",
        scan_history.fail_stale_running_scans,
        max_age_hours=6,
    )
    scan_history_deleted = _run_step(
        "scan_history_retention",
        scan_history.cleanup_old_scan_history,
        max_age_days=90,
    )
    notifications_deleted = _run_step(
        "notification_retention",
        notification_store.cleanup_old_notifications,
    )
    qcr_deleted = _run_step(
        "quality_result_retention",
        qcr_store.cleanup_old_results,
    )
    stale_backups_deleted = _run_step(
        "stale_backups",
        backup_store.cleanup_stale_backup_records,
        max_age_days=30,
    )
    expired_backups_deleted = _run_step(
        "expired_backups",
        backup_store.cleanup_expired_backup_records,
    )

    result = {
        "stale_tasks": task_cleanup,
        "stale_running_scans_failed": stale_scan_failures,
        "scan_history_deleted": scan_history_deleted,
        "notifications_deleted": notifications_deleted,
        "quality_results_deleted": qcr_deleted,
        "stale_backups_deleted": stale_backups_deleted,
        "expired_backups_deleted": expired_backups_deleted,
    }

    logger.info(
        "daily_maintenance_completed",
        stale_tasks=task_cleanup.get("cancelled_count", 0) if isinstance(task_cleanup, dict) else 0,
        stale_running_scans_failed=stale_scan_failures if isinstance(stale_scan_failures, int) else 0,
        scan_history_deleted=scan_history_deleted if isinstance(scan_history_deleted, int) else 0,
        notifications_deleted=sum(notifications_deleted.values()) if isinstance(notifications_deleted, dict) else 0,
        quality_results_deleted=sum(qcr_deleted.values()) if isinstance(qcr_deleted, dict) else 0,
        stale_backups_deleted=stale_backups_deleted,
        expired_backups_deleted=expired_backups_deleted,
    )
    return result
