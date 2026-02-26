"""Scheduled backup execution."""

from __future__ import annotations

from typing import Any

from ..logging_config import get_logger
from ..storage import backups as backup_store
from .backup_executor import create_backup
from .backup_utils import calculate_next_run

logger = get_logger(__name__)


def _cleanup_stale_records() -> None:
    """Remove stale backup records older than 30 days."""
    cleaned = backup_store.cleanup_stale_backup_records(max_age_days=30)
    if cleaned:
        logger.info("cleaned_stale_backup_records", count=cleaned)


def _process_due_source(source: dict[str, Any]) -> dict[str, Any]:
    """Trigger a backup for a single due source and update its next run time.

    Args:
        source: A backup source record that is due for execution.

    Returns:
        A result dict with source_id and next_run timestamp.
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

    create_backup(
        project_id=project_id,
        backup_type="scheduled",
        note=f"Scheduled {frequency} backup",
        retention_days=retention_days,
        source_id=source_id,
    )

    next_run = calculate_next_run(frequency)
    backup_store.update_source_last_run(source_id, next_run)

    return {
        "source_id": source_id,
        "next_run": next_run.isoformat() if next_run else None,
    }


def _cleanup_expired_records() -> None:
    """Remove expired completed backup records to keep the DB in sync."""
    expired = backup_store.cleanup_expired_backup_records()
    if expired:
        logger.info("cleaned_expired_backup_records", count=expired)


def run_scheduled_backups() -> dict[str, Any]:
    """Check and run due scheduled backups.

    Queries backup_sources for any that are due and triggers backups.

    Returns:
        Summary of scheduled backups run
    """
    logger.info("run_scheduled_backups_started")

    _cleanup_stale_records()

    due_sources = backup_store.list_due_sources()

    if not due_sources:
        logger.info("no_scheduled_backups_due")
        return {"status": "success", "message": "No scheduled backups due", "count": 0}

    results = [_process_due_source(source) for source in due_sources]

    _cleanup_expired_records()

    logger.info("run_scheduled_backups_completed", count=len(results))

    return {
        "status": "success",
        "count": len(results),
        "results": results,
    }
