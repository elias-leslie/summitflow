"""Daily maintenance orchestration for retention and stale-record recovery."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from ..logging_config import get_logger
from ..storage import backups as backup_store
from ..storage import events as event_store
from ..storage import maintenance_runs as maintenance_store
from ..storage import notifications as notification_store
from ..storage import quality_check_results as qcr_store
from ..storage import scan_history
from ..storage.tasks import purge_terminal_tasks
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


def _step_failed(result: Any) -> bool:
    return isinstance(result, dict) and "error" in result


def _deleted_count(result: Any) -> int:
    if isinstance(result, bool):
        return 0
    if isinstance(result, int):
        return result
    if isinstance(result, dict):
        total_deleted = result.get("total_deleted")
        if isinstance(total_deleted, int) and not isinstance(total_deleted, bool):
            return total_deleted
        return sum(value for value in result.values() if isinstance(value, int) and not isinstance(value, bool))
    return 0


def run_daily_maintenance(
    max_age_days: int = 30,
    *,
    notification_pending_age_days: int = 90,
) -> dict[str, Any]:
    """Run the daily retention and stale-state cleanup workflow."""
    started_at = datetime.now(UTC)
    logger.info("daily_maintenance_started", max_age_days=max_age_days)

    try:
        task_cleanup = _run_step("stale_tasks", cleanup_stale_tasks, max_age_days)
        task_purge = _run_step(
            "purge_terminal_tasks",
            purge_terminal_tasks,
            completed_max_age_days=30,
        )
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
            max_pending_age_days=notification_pending_age_days,
        )
        qcr_deleted = _run_step(
            "quality_result_retention",
            qcr_store.cleanup_old_results,
        )
        events_deleted = _run_step(
            "event_retention",
            event_store.cleanup_old_events,
        )
        maintenance_runs_deleted = _run_step(
            "maintenance_run_retention",
            maintenance_store.cleanup_old_maintenance_runs,
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

        rows_cleaned = sum(
            [
                _deleted_count(
                    task_cleanup.get("cancelled_count", 0)
                    if isinstance(task_cleanup, dict)
                    else task_cleanup
                ),
                _deleted_count(task_purge),
                _deleted_count(stale_scan_failures),
                _deleted_count(scan_history_deleted),
                _deleted_count(notifications_deleted),
                _deleted_count(qcr_deleted),
                _deleted_count(events_deleted),
                _deleted_count(maintenance_runs_deleted),
                _deleted_count(stale_backups_deleted),
                _deleted_count(expired_backups_deleted),
            ]
        )
        result = {
            "status": "partial"
            if any(
                _step_failed(step)
                for step in (
                    task_cleanup,
                    task_purge,
                    stale_scan_failures,
                    scan_history_deleted,
                    notifications_deleted,
                    qcr_deleted,
                    events_deleted,
                    maintenance_runs_deleted,
                    stale_backups_deleted,
                    expired_backups_deleted,
                )
            )
            else "success",
            "rows_cleaned": rows_cleaned,
            "stale_tasks": task_cleanup,
            "purged_tasks": task_purge,
            "stale_running_scans_failed": stale_scan_failures,
            "scan_history_deleted": scan_history_deleted,
            "notifications_deleted": notifications_deleted,
            "quality_results_deleted": qcr_deleted,
            "events_deleted": events_deleted,
            "maintenance_runs_deleted": maintenance_runs_deleted,
            "stale_backups_deleted": stale_backups_deleted,
            "expired_backups_deleted": expired_backups_deleted,
        }
        finished_at = datetime.now(UTC)
        maintenance_store.record_maintenance_run(
            "daily_maintenance",
            result["status"],
            started_at=started_at,
            finished_at=finished_at,
            rows_cleaned=rows_cleaned,
            summary=result,
        )

        logger.info(
            "daily_maintenance_completed",
            status=result["status"],
            rows_cleaned=rows_cleaned,
            stale_tasks=_deleted_count(task_cleanup.get("cancelled_count", 0) if isinstance(task_cleanup, dict) else task_cleanup),
            purged_tasks=_deleted_count(task_purge),
            stale_running_scans_failed=_deleted_count(stale_scan_failures),
            scan_history_deleted=_deleted_count(scan_history_deleted),
            notifications_deleted=_deleted_count(notifications_deleted),
            quality_results_deleted=_deleted_count(qcr_deleted),
            events_deleted=_deleted_count(events_deleted),
            maintenance_runs_deleted=_deleted_count(maintenance_runs_deleted),
            stale_backups_deleted=_deleted_count(stale_backups_deleted),
            expired_backups_deleted=_deleted_count(expired_backups_deleted),
        )
        return result
    except Exception as exc:
        finished_at = datetime.now(UTC)
        maintenance_store.record_maintenance_run(
            "daily_maintenance",
            "failed",
            started_at=started_at,
            finished_at=finished_at,
            rows_cleaned=0,
            summary={},
            error_message=str(exc),
        )
        raise
