"""Scheduled backup execution."""

from __future__ import annotations

from typing import Any

from ..logging_config import get_logger
from ..storage import backups as backup_store
from .backup_executor import create_backup
from .backup_utils import calculate_next_run

logger = get_logger(__name__)


def run_scheduled_backups() -> dict[str, Any]:
    """Check and run due scheduled backups.

    Queries backup_sources for any that are due and triggers backups.

    Returns:
        Summary of scheduled backups run
    """
    logger.info("run_scheduled_backups_started")

    # Clean up stale backup records (failed/running older than 30 days)
    cleaned = backup_store.cleanup_stale_backup_records(max_age_days=30)
    if cleaned:
        logger.info("cleaned_stale_backup_records", count=cleaned)

    due_sources = backup_store.list_due_sources()

    if not due_sources:
        logger.info("no_scheduled_backups_due")
        return {"status": "success", "message": "No scheduled backups due", "count": 0}

    results: list[dict[str, Any]] = []

    for source in due_sources:
        source_id = source["id"]
        project_id = source.get("project_id") or source_id
        frequency = source["frequency"]

        logger.info(
            "triggering_scheduled_backup",
            source_id=source_id,
            frequency=frequency,
        )

        retention_days = source.get("retention_days")

        # Run backup directly (Hatchet handles async scheduling)
        create_backup(
            project_id=project_id,
            backup_type="scheduled",
            note=f"Scheduled {frequency} backup",
            retention_days=retention_days,
            source_id=source_id,
        )

        # Calculate next run time
        next_run = calculate_next_run(frequency)
        backup_store.update_source_last_run(source_id, next_run)

        results.append(
            {
                "source_id": source_id,
                "next_run": next_run.isoformat() if next_run else None,
            }
        )

    # Clean up expired completed backup records to keep DB in sync
    expired = backup_store.cleanup_expired_backup_records()
    if expired:
        logger.info("cleaned_expired_backup_records", count=expired)

    logger.info("run_scheduled_backups_completed", count=len(results))

    return {
        "status": "success",
        "count": len(results),
        "results": results,
    }
