"""The worker's hourly backup tick: housekeeping and health. It starts no backup.

Backups run from systemd (``backup_run``, summitflow-host-backup.timer). This tick only tidies what a killed run
leaves behind, ages out the records and archives of the retired per-project backups, and refreshes the health
receipts and alerts, so a timer that stopped firing is noticed from a second place.
"""

from __future__ import annotations

import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..logging_config import get_logger
from ..storage import backups as backup_store
from ..storage import maintenance_runs as maintenance_store
from ..utils.transient_scratch import SCRATCH_ROOT
from .backup_local_cleanup import cleanup_local_backup_archives

logger = get_logger(__name__)
STALE_RUNNING_AGE_MINUTES = 30
# Transient backup scratch untouched this long and open by no process is residue.
SCRATCH_RESIDUE_HOURS = 24


def _cleanup_stale_records() -> int:
    """Remove stale backup records older than 30 days."""
    cleaned = backup_store.cleanup_stale_backup_records(max_age_days=30)
    if cleaned:
        logger.info("cleaned_stale_backup_records", count=cleaned)
    return cleaned


def _fail_stale_running_records() -> int:
    """Fail old rows of the retired per-project backups that were left running; nothing holds a lease any more."""
    failed = backup_store.fail_stale_running_backups(
        max_age_minutes=STALE_RUNNING_AGE_MINUTES, is_source_active=lambda _source_id: False,
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


def run_scheduled_backups() -> dict[str, Any]:
    """Housekeeping, then the health pass. Returns a summary for the maintenance record."""
    started_at = datetime.now(UTC)
    housekeeping = _housekeeping()
    stale_cleaned = _cleanup_stale_records()
    expired_count = _cleanup_expired_records()
    local_cleanup = _cleanup_local_archives()
    result: dict[str, Any] = {
        "status": "success", "stale_failed": int(housekeeping.get("stale_failed") or 0), "stale_cleaned": stale_cleaned,
        "expired_cleaned": expired_count, "local_archives_deleted": int(local_cleanup.get("deleted") or 0),
        "local_bytes_deleted": int(local_cleanup.get("bytes_deleted") or 0), "housekeeping": housekeeping,
    }
    result["rows_cleaned"] = result["stale_failed"] + stale_cleaned + expired_count
    _evaluate_alerts(result)
    maintenance_store.record_maintenance_run(
        "scheduled_backups", result["status"], started_at=started_at, finished_at=datetime.now(UTC),
        rows_cleaned=result["rows_cleaned"], summary=result,
    )
    return result
