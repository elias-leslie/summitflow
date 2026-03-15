"""Scheduled backup execution."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ..logging_config import get_logger
from ..storage import backups as backup_store
from ..storage import maintenance_runs as maintenance_store
from .backup_executor import create_backup
from .backup_utils import calculate_next_run

logger = get_logger(__name__)


def _cleanup_stale_records() -> int:
    """Remove stale backup records older than 30 days."""
    cleaned = backup_store.cleanup_stale_backup_records(max_age_days=30)
    if cleaned:
        logger.info("cleaned_stale_backup_records", count=cleaned)
    return cleaned


def _process_due_source(source: dict[str, Any]) -> dict[str, Any]:
    """Trigger a backup for a single due source.

    Args:
        source: A backup source record that is due for execution.

    Returns:
        A result dict with source_id, status, and optional next_run/error data.
    """
    source_id = source["id"]
    project_id = source.get("project_id") or source_id  # non-project sources use source_id
    frequency = source["frequency"]
    retention_days = source.get("retention_days")

    logger.info(
        "triggering_scheduled_backup",
        source_id=source_id,
        frequency=frequency,
    )

    result = create_backup(
        project_id=project_id,
        backup_type="scheduled",
        note=f"Scheduled {frequency} backup",
        retention_days=retention_days,
        source_id=source_id,
    )

    status = str(result.get("status", "unknown"))
    if status not in ("completed", "completed_pending_upload"):
        logger.warning(
            "scheduled_backup_source_failed",
            source_id=source_id,
            frequency=frequency,
            status=status,
            error=result.get("error"),
        )
        return {
            "source_id": source_id,
            "status": status,
            "error": result.get("error"),
        }

    next_run = calculate_next_run(frequency)
    backup_store.update_source_last_run(source_id, next_run)
    return {
        "source_id": source_id,
        "status": status,
        "next_run": next_run.isoformat() if next_run else None,
        "backup_id": result.get("backup_id"),
    }


def _cleanup_expired_records() -> int:
    """Remove expired completed backup records to keep the DB in sync."""
    expired = backup_store.cleanup_expired_backup_records()
    if expired:
        logger.info("cleaned_expired_backup_records", count=expired)
    return expired


def run_scheduled_backups() -> dict[str, Any]:
    """Check and run due scheduled backups.

    Queries backup_sources for any that are due and triggers backups.

    Returns:
        Summary of scheduled backups run
    """
    started_at = datetime.now(UTC)
    logger.info("run_scheduled_backups_started")

    try:
        stale_cleaned = _cleanup_stale_records()
        expired_count = _cleanup_expired_records()

        due_sources = backup_store.list_due_sources()

        if not due_sources:
            result = {
                "status": "success",
                "message": "No scheduled backups due",
                "count": 0,
                "succeeded": 0,
                "failed": 0,
                "stale_cleaned": stale_cleaned,
                "expired_cleaned": expired_count,
                "rows_cleaned": stale_cleaned + expired_count,
                "results": [],
            }
            maintenance_store.record_maintenance_run(
                "scheduled_backups",
                result["status"],
                started_at=started_at,
                finished_at=datetime.now(UTC),
                rows_cleaned=result["rows_cleaned"],
                summary=result,
            )
            logger.info(
                "no_scheduled_backups_due",
                stale_cleaned=stale_cleaned,
                expired_cleaned=expired_count,
            )
            return result

        results: list[dict[str, Any]] = []
        for source in due_sources:
            try:
                results.append(_process_due_source(source))
            except Exception as exc:
                logger.exception(
                    "scheduled_backup_source_unhandled_error",
                    source_id=source.get("id"),
                )
                results.append(
                    {
                        "source_id": source.get("id"),
                        "status": "error",
                        "error": str(exc),
                    }
                )

        succeeded = sum(1 for result in results if result.get("status") == "completed")
        failed = len(results) - succeeded
        result = {
            "status": "success" if failed == 0 else "partial",
            "count": len(results),
            "succeeded": succeeded,
            "failed": failed,
            "stale_cleaned": stale_cleaned,
            "expired_cleaned": expired_count,
            "rows_cleaned": stale_cleaned + expired_count,
            "results": results,
        }
        maintenance_store.record_maintenance_run(
            "scheduled_backups",
            result["status"],
            started_at=started_at,
            finished_at=datetime.now(UTC),
            rows_cleaned=result["rows_cleaned"],
            summary=result,
        )

        logger.info(
            "run_scheduled_backups_completed",
            count=len(results),
            succeeded=succeeded,
            failed=failed,
            stale_cleaned=stale_cleaned,
            expired_cleaned=expired_count,
        )
        return result
    except Exception as exc:
        maintenance_store.record_maintenance_run(
            "scheduled_backups",
            "failed",
            started_at=started_at,
            finished_at=datetime.now(UTC),
            rows_cleaned=0,
            summary={},
            error_message=str(exc),
        )
        raise
