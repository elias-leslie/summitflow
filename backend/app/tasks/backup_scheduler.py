"""Scheduled backup execution."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from ..config import get_settings
from ..logging_config import get_logger
from ..storage import backups as backup_store
from ..storage import maintenance_runs as maintenance_store
from .backup_executor import create_backup
from .backup_local_cleanup import cleanup_local_backup_archives
from .backup_lock import has_active_backup_lease
from .backup_utils import _FREQUENCY_DELTAS, calculate_next_run

logger = get_logger(__name__)
SUCCESS_STATUSES = {"completed", "completed_pending_upload"}
STALE_RUNNING_AGE_MINUTES = 30


def _scheduled_backup_window_open(now: datetime) -> bool:
    """Allow scheduled work within the optional local-time window, including DST."""
    settings = get_settings()
    start = settings.backup_schedule_start_hour
    end = settings.backup_schedule_end_hour
    if start is None or end is None:
        return True
    hour = now.astimezone(ZoneInfo(settings.backup_schedule_timezone)).hour
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


def _latest_finished_window_end(now: datetime) -> datetime:
    settings = get_settings()
    local = now.astimezone(ZoneInfo(settings.backup_schedule_timezone))
    end = local.replace(hour=settings.backup_schedule_end_hour or 0, minute=0, second=0, microsecond=0, fold=0)
    if end.astimezone(UTC) > now.astimezone(UTC):
        end -= timedelta(days=1)
    return end.astimezone(UTC)


def _catchup_source(source: dict[str, Any], finished_window_end: datetime) -> bool:
    """Only recover persisted overdue work, never a newly due daytime source."""
    if source.get("enabled") is False:
        return False
    due = source.get("next_run_at")
    if not due:
        last_run = source.get("last_run_at")
        if last_run:
            if isinstance(last_run, str):
                last_run = datetime.fromisoformat(last_run)
            due = last_run + _FREQUENCY_DELTAS.get(source.get("frequency", "daily"), timedelta(days=1))
        else:
            # An initial source's registration time proves whether it existed
            # during a missed window.
            due = source.get("created_at")
    if not due:
        return False
    if isinstance(due, str):
        due = datetime.fromisoformat(due)
    if due.tzinfo is None:
        due = due.replace(tzinfo=UTC)
    return bool(due < finished_window_end)


def _align_next_run_to_window(next_run: datetime, now: datetime) -> datetime:
    settings = get_settings()
    start = settings.backup_schedule_start_hour
    if start is None:
        return next_run
    local = next_run.astimezone(ZoneInfo(settings.backup_schedule_timezone))
    aligned = local.replace(hour=start, minute=0, second=0, microsecond=0, fold=0)
    if aligned.astimezone(UTC) <= now.astimezone(UTC):
        aligned += timedelta(days=1)
    return aligned.astimezone(UTC)


def _cleanup_stale_records() -> int:
    """Remove stale backup records older than 30 days."""
    cleaned = backup_store.cleanup_stale_backup_records(max_age_days=30)
    if cleaned:
        logger.info("cleaned_stale_backup_records", count=cleaned)
    return cleaned


def _fail_stale_running_records() -> int:
    """Fail old orphaned rows without imposing a total runtime on live backups."""
    failed = backup_store.fail_stale_running_backups(
        max_age_minutes=STALE_RUNNING_AGE_MINUTES, is_source_active=has_active_backup_lease,
    )
    if failed:
        logger.warning("failed_stale_running_backups", count=failed)
    return failed


def _process_due_source(
    source: dict[str, Any], *, on_progress: Callable[[], None] | None = None,
) -> dict[str, Any]:
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

    publication: dict[str, Any] | None = None
    if get_settings().backup_publish_before_backup:
        from .backup_publish import publish_source_before_backup
        try:
            publication = publish_source_before_backup(source)
        except Exception:
            # Publication is useful redundancy, never a prerequisite for WIP
            # recovery. Avoid persisting raw Git/OAuth diagnostics.
            logger.warning("backup_publication_failed", source_id=source_id)
            publication = {"status": "failed", "reason": "publication-unavailable"}

    result = create_backup(
        project_id=project_id,
        backup_type="scheduled",
        note=f"Scheduled {frequency} backup",
        retention_days=retention_days,
        source_id=source_id,
        on_progress=on_progress,
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

    if publication is not None and result.get("backup_id"):
        try:
            backup_store.merge_backup_verification_json(str(result["backup_id"]), {"publication": publication})
        except Exception:
            logger.warning("backup_publication_evidence_failed", source_id=source_id)

    next_run = calculate_next_run(frequency)
    if frequency in {"daily", "weekly", "monthly"}:
        next_run = _align_next_run_to_window(next_run, datetime.now(UTC))
    backup_store.update_source_last_run(source_id, next_run)
    return {
        "source_id": source_id,
        "status": status,
        "next_run": next_run.isoformat() if next_run else None,
        "backup_id": result.get("backup_id"),
        **({"publication": publication} if publication is not None else {}),
    }


def _cleanup_expired_records() -> int:
    """Remove expired completed backup records to keep the DB in sync."""
    expired = backup_store.cleanup_expired_backup_records()
    if expired:
        logger.info("cleaned_expired_backup_records", count=expired)
    return expired


def _cleanup_local_archives() -> dict[str, Any]:
    """Remove local archive files whose DB rows already expired."""
    result = cleanup_local_backup_archives(dry_run=False)
    if result.get("deleted"):
        logger.info(
            "cleaned_local_backup_archives",
            count=result.get("deleted"),
            bytes_deleted=result.get("bytes_deleted"),
        )
    if result.get("failed"):
        logger.warning(
            "local_backup_archive_cleanup_failures",
            count=result.get("failed"),
        )
    return result


def run_scheduled_backups(*, on_progress: Callable[[], None] | None = None) -> dict[str, Any]:
    """Check and run due scheduled backups.

    Queries backup_sources for any that are due and triggers backups.

    Returns:
        Summary of scheduled backups run
    """
    started_at = datetime.now(UTC)
    window_open = _scheduled_backup_window_open(started_at)
    logger.info("run_scheduled_backups_started")

    try:
        due_sources = backup_store.list_due_sources()
        if not window_open:
            window_end = _latest_finished_window_end(started_at)
            due_sources = [source for source in due_sources if _catchup_source(source, window_end)]
            if not due_sources:
                logger.info("scheduled_backups_outside_window")
                return {"status": "skipped", "reason": "outside-backup-window", "count": 0, "results": []}
            logger.info("scheduled_backups_catching_up", count=len(due_sources))
        stale_failed = _fail_stale_running_records()
        stale_cleaned = _cleanup_stale_records() if window_open else 0
        expired_count = _cleanup_expired_records() if window_open else 0
        local_cleanup = _cleanup_local_archives() if window_open else {}
        local_archives_deleted = int(local_cleanup.get("deleted") or 0)
        local_bytes_deleted = int(local_cleanup.get("bytes_deleted") or 0)

        results: list[dict[str, Any]] = []
        for source in due_sources:
            try:
                results.append(_process_due_source(source, on_progress=on_progress))
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

        succeeded = sum(1 for result in results if result.get("status") in SUCCESS_STATUSES)
        failed = len(results) - succeeded
        result: dict[str, Any] = {
            "status": "success" if failed == 0 else "partial",
            "count": len(results),
            "succeeded": succeeded,
            "failed": failed,
            "stale_failed": stale_failed,
            "stale_cleaned": stale_cleaned,
            "expired_cleaned": expired_count,
            "local_archives_deleted": local_archives_deleted,
            "local_bytes_deleted": local_bytes_deleted,
            "rows_cleaned": stale_failed + stale_cleaned + expired_count,
            "results": results,
            "catch_up": not window_open,
        }
        if not due_sources:
            result["message"] = "No scheduled backups due"

        # Restore drill cadence is independent of whether any backup is due.
        try:
            result["drill"] = run_scheduled_drills() if window_open else {"status": "skipped", "reason": "outside-backup-window"}
        except Exception:
            logger.exception("scheduled_drill_failed")
            result["drill"] = {"status": "error"}

        try:
            from .backup_repository_runtime import (
                repository_maintenance_failed,
                run_repository_maintenance,
            )

            repositories = run_repository_maintenance() if window_open else []
            if repositories:
                result["repository_maintenance"] = repositories
                if repository_maintenance_failed(repositories):
                    result["status"] = "partial"
        except Exception:
            logger.exception("scheduled_repository_maintenance_failed")
            result["repository_maintenance"] = {"status": "error"}
            result["status"] = "partial"

        from .backup_restic_pilot import run_daily_restic_pilot

        pilot = run_daily_restic_pilot(on_progress=on_progress) if window_open else {"reason": "pilot-disabled"}
        if pilot.get("reason") != "pilot-disabled":
            result["restic_daily_pilot"] = pilot
            if pilot.get("status") in {"failed", "incomplete"} or pilot.get("daily_status") in {"failed", "incomplete"}:
                result["status"] = "partial"

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
            stale_failed=stale_failed,
            stale_cleaned=stale_cleaned,
            expired_cleaned=expired_count,
            local_archives_deleted=local_archives_deleted,
            local_bytes_deleted=local_bytes_deleted,
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


def run_scheduled_drills() -> dict[str, Any]:
    """Use repository offsite recovery, otherwise the existing daily drill.

    Returns:
        Drill result summary.
    """
    sources = backup_store.list_sources()
    infra_source = next((s for s in sources if s.get("source_type") == "infrastructure" and s.get("enabled")), None)

    if not infra_source:
        return {"status": "skipped", "reason": "no enabled infrastructure source"}

    # The repository manager already restores offsite PostgreSQL/Redis and
    # configuration weekly. Do not rebuild those databases locally every day
    # as well. Resolve the effective source backend, including overrides.
    from .backup_utils import get_storage_config

    config = get_storage_config(str(infra_source["id"])) or {}
    if config.get("engine") == "restic" and config.get("restic_remote_repository"):
        return {"status": "skipped", "reason": "repository-managed-weekly-offsite-drill", "backend_id": config.get("__backend_id")}

    # Check staleness — only drill if >24h old
    last_drill_at = infra_source.get("last_drill_at")
    if last_drill_at:
        try:
            dt = datetime.fromisoformat(str(last_drill_at))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            hours_since = (datetime.now(UTC) - dt).total_seconds() / 3600
            if hours_since < 24:
                logger.info("scheduled_drill_skipped", hours_since=round(hours_since, 1))
                return {"status": "skipped", "reason": f"last drill {round(hours_since, 1)}h ago"}
        except (ValueError, TypeError):
            pass  # Proceed with drill if we can't parse

    logger.info("scheduled_drill_started")
    from .backup_restore_drill import run_infra_drill

    result = run_infra_drill()
    logger.info("scheduled_drill_completed", ok=result.get("ok"))
    return {"status": "completed", "ok": result.get("ok"), "result": result}
