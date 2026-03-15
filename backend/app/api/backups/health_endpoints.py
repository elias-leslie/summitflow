"""Backup health monitoring endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from ...storage import backups as backup_store
from ...tasks.backup_wal import get_wal_status
from .models import BackupHealthItem, BackupHealthResponse, WalHealthSummary

router = APIRouter()


@router.get("/backups/health", response_model=BackupHealthResponse)
async def backup_health() -> BackupHealthResponse:
    """Per-source backup health: last success, next run, failure count (7d), pending uploads, restore readiness."""
    rows = backup_store.get_backup_health_summary()
    items = []
    total_pending_upload = 0

    for row in rows:
        failure_count = row.get("failure_count_7d", 0)
        last_success = row.get("last_success_at")
        last_status = row.get("last_backup_status")
        pending_upload_count = row.get("pending_upload_count", 0)
        total_pending_upload += pending_upload_count

        # Health logic:
        # - red: most recent backup failed
        # - yellow: pending upload, never succeeded, or restore never tested
        # - green: most recent backup succeeded
        if last_status == "failed":
            health_status = "red"
        elif last_status == "completed_pending_upload":
            health_status = "yellow"
        elif last_success:
            health_status = "green"
        else:
            health_status = "yellow"

        items.append(
            BackupHealthItem(
                source_id=row["source_id"],
                source_name=row["source_name"],
                source_type=row["source_type"],
                enabled=row["enabled"],
                health_status=health_status,
                last_success_at=last_success,
                next_run_at=row.get("next_run_at"),
                failure_count_7d=failure_count,
                pending_upload_count=pending_upload_count,
                last_restore_tested_at=row.get("last_restore_tested_at"),
                last_restore_test_ok=row.get("last_restore_test_ok"),
            )
        )

    # WAL summary
    wal: WalHealthSummary | None = None
    try:
        wal_data = get_wal_status()
        wal = WalHealthSummary(
            enabled=wal_data.get("enabled", False),
            archive_segment_count=wal_data.get("archive_segment_count", 0),
            archive_size_bytes=wal_data.get("archive_size_bytes", 0),
            last_archived_time=wal_data.get("last_archived_time"),
            failed_count=wal_data.get("failed_count", 0),
        )
    except Exception:
        pass

    return BackupHealthResponse(
        sources=items,
        pending_upload_count=total_pending_upload,
        wal=wal,
    )


@router.post("/backups/restore-test/all")
async def restore_test_all() -> dict:
    """Run dry-run restore tests for all enabled backup sources."""
    from ...tasks.backup_restore_test import run_restore_tests

    return run_restore_tests()


@router.post("/backups/drain-pending")
async def drain_pending(dry_run: bool = False) -> dict:
    """Drain pending backup uploads to SMB."""
    from ...tasks.backup_drain import drain_pending_backups

    return drain_pending_backups(dry_run=dry_run)
