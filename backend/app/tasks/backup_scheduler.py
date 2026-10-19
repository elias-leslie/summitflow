"""Scheduled backup execution."""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from ..config import get_settings
from ..logging_config import get_logger
from ..storage import backups as backup_store
from ..storage import maintenance_runs as maintenance_store
from ..utils.maintenance_window import MaintenanceWindow
from ..utils.transient_scratch import SCRATCH_ROOT
from .backup_executor import create_backup
from .backup_local_cleanup import cleanup_local_backup_archives
from .backup_lock import backup_lease_holder_dead, has_active_backup_lease
from .backup_utils import _FREQUENCY_DELTAS, calculate_next_run

logger = get_logger(__name__)
SUCCESS_STATUSES = {"completed", "completed_pending_upload"}
# An owner-powered-off source is retried each tick without counting as a failure.
NON_FAILURE_STATUSES = SUCCESS_STATUSES | {"offline"}
STALE_RUNNING_AGE_MINUTES = 30
# A row whose lease holder is provably dead needs no 30-minute wait.
DEAD_HOLDER_AGE_MINUTES = 1
# Transient backup scratch untouched this long and open by no process is residue.
SCRATCH_RESIDUE_HOURS = 24


def _schedule_window() -> tuple[MaintenanceWindow, ZoneInfo] | None:
    """The scheduled-backup window (shared maintenance-window format) and the clock it reads in; None = unrestricted."""
    settings = get_settings()
    if not settings.backup_schedule_window:
        return None
    return MaintenanceWindow.parse(settings.backup_schedule_window), ZoneInfo(settings.backup_schedule_timezone)


def _scheduled_backup_window_open(now: datetime) -> bool:
    """Allow scheduled work within the optional window, in wall-clock time (daylight saving included)."""
    window = _schedule_window()
    return True if window is None else window[0].contains(now, window[1])


def _latest_finished_window_end(now: datetime) -> datetime:
    window = _schedule_window()
    return now.astimezone(UTC) if window is None else window[0].latest_end(now, window[1])


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
    window = _schedule_window()
    if window is None:
        return next_run
    return window[0].align_start(next_run, now, window[1])


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
    failed += backup_store.fail_stale_running_backups(
        max_age_minutes=DEAD_HOLDER_AGE_MINUTES,
        is_source_active=lambda source_id: not backup_lease_holder_dead(source_id),
        error_message="Backup worker stopped mid-run (restart or kill); its lease holder is no longer running",
    )
    if failed:
        logger.warning("failed_stale_running_backups", count=failed)
    return failed


def _open_paths() -> set[Path]:
    paths: set[Path] = set()
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            links = [proc / "cwd", *(proc / "fd").iterdir()]
        except OSError:
            links = [proc / "cwd"]
        for link in links:
            try:
                paths.add(Path(os.readlink(link)))
            except OSError:
                continue
    return paths


def _reap_backup_scratch(now: datetime | None = None) -> dict[str, int]:
    """Remove transient backup/restore scratch and isolated acceptance clones left by killed attempts.

    Every job directory belongs to one attempt; one untouched for a day and
    open by no process can never be resumed (restic caches are rebuilt). A
    SIGKILLed isolated acceptance leaks its st-a-* clone (about 600 MB).
    """
    cutoff = (now or datetime.now(UTC)).timestamp() - SCRATCH_RESIDUE_HOURS * 3600
    removed = reclaimed = 0
    parents = [SCRATCH_ROOT / f"{namespace}-{os.getuid()}" for namespace in ("st-backups", "st-restores", "st-acceptance")]
    candidates = [entry for parent in parents if parent.is_dir() and not parent.is_symlink() for entry in parent.iterdir()]
    if not candidates:
        return {"removed": 0, "bytes": 0}
    in_use = _open_paths()
    for entry in candidates:
        if entry.is_symlink() or not entry.is_dir():
            continue
        try:
            newest = max([entry.lstat().st_mtime, *(path.lstat().st_mtime for path in entry.rglob("*"))])
            size = sum(path.lstat().st_size for path in entry.rglob("*") if path.is_file() and not path.is_symlink())
        except OSError:
            continue
        if newest > cutoff or any(path == entry or path.is_relative_to(entry) for path in in_use):
            continue
        shutil.rmtree(entry, ignore_errors=True)
        if not entry.exists():
            removed += 1
            reclaimed += size
    if removed:
        logger.info("reaped_backup_scratch", count=removed, bytes=reclaimed)
    return {"removed": removed, "bytes": reclaimed}


def _housekeeping() -> dict[str, Any]:
    """Self-healing steps that must run every tick, inside or outside the window."""
    result: dict[str, Any] = {}
    try:
        result["stale_failed"] = _fail_stale_running_records()
    except Exception as exc:
        logger.exception("stale_running_reap_failed")
        result["stale_failed"], result["stale_error"] = 0, str(exc)
    try:
        result["scratch"] = _reap_backup_scratch()
    except Exception as exc:
        logger.exception("backup_scratch_reap_failed")
        result["scratch"] = {"error": str(exc)}
    return result


def _evaluate_alerts(summary: dict[str, Any]) -> None:
    try:
        from .backup_alerts import evaluate_backup_alerts

        summary["alerts"] = evaluate_backup_alerts(summary)
    except Exception as exc:
        logger.exception("backup_alert_evaluation_failed")
        summary["alerts"] = {"error": str(exc)}


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

    result = create_backup(
        project_id=project_id,
        backup_type="scheduled",
        note=f"Scheduled {frequency} backup",
        retention_days=retention_days,
        source_id=source_id,
        on_progress=on_progress,
    )

    status = str(result.get("status", "unknown"))
    if status == "offline":
        from .backup_alerts import mark_source_offline

        logger.info("scheduled_backup_source_offline", source_id=source_id)
        mark_source_offline(source_id)
        return {"source_id": source_id, "status": status, "reason": result.get("reason")}
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
    if frequency in {"daily", "weekly", "monthly"}:
        next_run = _align_next_run_to_window(next_run, datetime.now(UTC))
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


def _scheduled_host_backup(now: datetime) -> dict[str, Any]:
    try:
        from .backup_btrbk import run_scheduled_host_backup

        return run_scheduled_host_backup(now)
    except Exception as exc:
        logger.exception("scheduled_host_backup_failed")
        return {"status": "failed", "error": str(exc)}


def _copy_and_health(window_open: bool) -> dict[str, Any]:
    """Append-only PVE copy and weekly health; never fails the scheduled run."""
    try:
        from .backup_pve_copy import run_scheduled_copy_and_health

        return run_scheduled_copy_and_health(window_open=window_open)
    except Exception as exc:
        logger.exception("pve_copy_and_health_failed")
        return {"status": "error", "error": str(exc)[:300]}


def _reassociate_after_copy(host_backup: dict[str, Any], copies: dict[str, Any]) -> dict[str, Any]:
    """Judge database recovery against this tick's offsite copy, not the previous one.

    The host capture is associated before the copy step; when that left only the
    database association incomplete and the copy verified new points, retry the
    association (no new host capture: the retained points are reused).
    """
    if not (host_backup.get("capture_complete") and host_backup.get("reason") == "database-recovery-incomplete"):
        return host_backup
    if not any(value.get("status") == "verified" for value in (copies or {}).values()):
        return host_backup
    return _scheduled_host_backup(datetime.now(UTC))


def run_scheduled_backups(*, on_progress: Callable[[], None] | None = None) -> dict[str, Any]:
    """Check and run due scheduled backups.

    Queries backup_sources for any that are due and triggers backups.

    Returns:
        Summary of scheduled backups run
    """
    started_at = datetime.now(UTC)
    window_open = _scheduled_backup_window_open(started_at)
    logger.info("run_scheduled_backups_started")
    host_backup = _scheduled_host_backup(started_at)
    housekeeping = _housekeeping()

    try:
        from .backup_repository_runtime import repository_capture_batch, sync_repository_batch

        due_sources = backup_store.list_due_sources()
        if not window_open:
            window_end = _latest_finished_window_end(started_at)
            due_sources = [source for source in due_sources if source.get("frequency") == "four_hourly" or _catchup_source(source, window_end)]
            if not due_sources:
                logger.info("scheduled_backups_outside_window")
                # Persisted offsite backlog is independent of capture eligibility.
                # The batch helper retains repository serialization and capacity admission.
                copies = sync_repository_batch({})
                host_backup = _reassociate_after_copy(host_backup, copies)
                safety = _copy_and_health(window_open)
                skipped_result: dict[str, Any] = {"status": "partial" if host_backup.get("status") in {"blocked", "failed", "error", "partial", "cancelled"} else "skipped", "reason": "outside-backup-window", "count": 0, "results": [], "host_backup": host_backup, "housekeeping": housekeeping}
                skipped_result["pve_copy"] = safety
                if copies:
                    skipped_result["repository_copy"] = {key: {field: value.get(field) for field in ("status", "error", "reason")} for key, value in copies.items()}
                    if any(value.get("status") in {"pending", "blocked", "failed", "error"} for value in copies.values()):
                        skipped_result["status"] = "partial"
                    elif any(value.get("status") == "verified" for value in copies.values()) and skipped_result["status"] == "skipped":
                        skipped_result["status"] = "success"
                _evaluate_alerts(skipped_result)
                return skipped_result
            logger.info("scheduled_backups_catching_up", count=len(due_sources))
        stale_failed = int(housekeeping.get("stale_failed") or 0)
        stale_cleaned = _cleanup_stale_records() if window_open else 0
        expired_count = _cleanup_expired_records() if window_open else 0
        local_cleanup = _cleanup_local_archives() if window_open else {}
        local_archives_deleted = int(local_cleanup.get("deleted") or 0)
        local_bytes_deleted = int(local_cleanup.get("bytes_deleted") or 0)

        results: list[dict[str, Any]] = []
        with repository_capture_batch() as batch:
            for source in due_sources:
                try:
                    results.append(_process_due_source(source, on_progress=on_progress))
                except Exception as exc:
                    logger.exception("scheduled_backup_source_unhandled_error", source_id=source.get("id"))
                    results.append({"source_id": source.get("id"), "status": "error", "error": str(exc)})
        copies = sync_repository_batch(batch)
        host_backup = _reassociate_after_copy(host_backup, copies)
        safety = _copy_and_health(window_open)

        succeeded = sum(1 for result in results if result.get("status") in SUCCESS_STATUSES)
        offline = sum(1 for result in results if result.get("status") == "offline")
        failed = sum(1 for result in results if result.get("status") not in NON_FAILURE_STATUSES)
        result: dict[str, Any] = {
            "status": "success" if failed == 0 else "partial",
            "count": len(results),
            "succeeded": succeeded,
            "failed": failed,
            "offline": offline,
            "stale_failed": stale_failed,
            "stale_cleaned": stale_cleaned,
            "expired_cleaned": expired_count,
            "local_archives_deleted": local_archives_deleted,
            "local_bytes_deleted": local_bytes_deleted,
            "rows_cleaned": stale_failed + stale_cleaned + expired_count,
            "results": results,
            "catch_up": not window_open,
            "host_backup": host_backup,
            "housekeeping": housekeeping,
            "pve_copy": safety,
        }
        if host_backup.get("status") in {"blocked", "failed", "error", "partial", "cancelled"}:
            result["status"] = "partial"
        if not due_sources:
            result["message"] = "No scheduled backups due"
        if copies:
            result["repository_copy"] = {key: {field: value.get(field) for field in ("status", "error", "reason")} for key, value in copies.items()}
            if any(value.get("status") in {"pending", "blocked", "failed", "error"} for value in copies.values()):
                result["status"] = "partial"

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

        maintenance_store.record_maintenance_run(
            "scheduled_backups",
            result["status"],
            started_at=started_at,
            finished_at=datetime.now(UTC),
            rows_cleaned=result["rows_cleaned"],
            summary=result,
        )
        # Alerts read the run just recorded and the repository journals.
        _evaluate_alerts(result)

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
    if result.get("unsupported"):
        return {"status": "skipped", "reason": result["error"]}
    logger.info("scheduled_drill_completed", ok=result.get("ok"))
    return {"status": "completed", "ok": result.get("ok"), "result": result}
