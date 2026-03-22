"""Backup health monitoring endpoints."""

from __future__ import annotations

from datetime import UTC

from fastapi import APIRouter

from ...logging_config import get_logger
from ...storage import backups as backup_store
from ...tasks.backup_coverage import get_coverage_summary
from ...tasks.backup_wal import get_wal_status
from .models import (
    BackupHealthItem,
    BackupHealthResponse,
    CoverageResponse,
    WalHealthSummary,
)

logger = get_logger(__name__)

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

        last_restore_test_ok = row.get("last_restore_test_ok")
        source_type = row.get("source_type", "")

        # Drill fields (infrastructure sources only)
        last_drill_at = row.get("last_drill_at")
        last_drill_ok = row.get("last_drill_ok")
        last_drill_backup_id = row.get("last_drill_backup_id")

        # Compute ages
        latest_backup_age_hours = _hours_since(last_success)
        latest_restore_test_age_hours = _hours_since(row.get("last_restore_tested_at"))

        # Compute restore confidence
        restore_confidence = _compute_restore_confidence(
            source_type=source_type,
            last_drill_at=last_drill_at,
            last_drill_ok=last_drill_ok,
            last_restore_test_ok=last_restore_test_ok,
            last_restore_tested_at=row.get("last_restore_tested_at"),
        )

        # Health logic — tighter for infrastructure:
        # - red: most recent backup failed OR (infra: drill failed)
        # - yellow: pending upload, never succeeded, restore/drill stale or untested
        # - green: backup succeeded AND restore validation current
        if last_status == "failed" or (source_type == "infrastructure" and last_drill_ok is False):
            health_status = "red"
        elif last_status == "completed_pending_upload":
            health_status = "yellow"
        elif source_type == "infrastructure":
            # Infrastructure: green requires drill passed
            if last_success and last_drill_ok is True:
                health_status = "green"
            elif last_success:
                health_status = "yellow"
            else:
                health_status = "yellow"
        elif last_success and last_restore_test_ok is True:
            health_status = "green"
        elif last_success:
            health_status = "yellow"
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
                latest_backup_age_hours=latest_backup_age_hours,
                latest_restore_test_age_hours=latest_restore_test_age_hours,
                restore_confidence=restore_confidence,
                last_drill_at=last_drill_at,
                last_drill_ok=last_drill_ok,
                last_drill_backup_id=last_drill_backup_id,
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
        logger.warning("Failed to retrieve WAL status", exc_info=True)

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


@router.get("/backups/infra/coverage", response_model=CoverageResponse)
async def infra_coverage() -> CoverageResponse:
    """Return the infrastructure coverage contract with verification against the latest backup."""
    # Find latest infra backup's verification_json
    sources = backup_store.list_sources()
    infra_source = next((s for s in sources if s.get("source_type") == "infrastructure"), None)

    verification_json = None
    if infra_source:
        latest = backup_store.get_latest_backup(source_id=infra_source["id"])
        if latest:
            verification_json = latest.get("verification_json")

    summary = get_coverage_summary(verification_json)
    return CoverageResponse(**summary)


@router.post("/backups/restore-drill/infra")
async def restore_drill_infra() -> dict:
    """Run a full infrastructure restore drill against the latest backup."""
    from ...tasks.backup_restore_drill import run_infra_drill

    return run_infra_drill()


# ─── Helpers ─────────────────────────────────────────────────────


def _hours_since(iso_str: str | None) -> float | None:
    """Compute hours elapsed since an ISO timestamp string."""
    if not iso_str:
        return None
    from datetime import datetime

    try:
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        delta = datetime.now(UTC) - dt
        return round(delta.total_seconds() / 3600, 1)
    except (ValueError, TypeError):
        return None


def _compute_restore_confidence(
    *,
    source_type: str,
    last_drill_at: str | None,
    last_drill_ok: bool | None,
    last_restore_test_ok: bool | None,
    last_restore_tested_at: str | None,
) -> str:
    """Compute restore confidence level.

    Returns: "verified" | "stale" | "partial" | "untested"
    """
    if source_type == "infrastructure":
        # Infrastructure uses drill results
        if last_drill_ok is None:
            return "untested"
        if last_drill_ok is False:
            return "partial"
        # Drill passed — check staleness (48h threshold)
        hours = _hours_since(last_drill_at)
        if hours is not None and hours <= 48:
            return "verified"
        return "stale"

    # Non-infrastructure uses restore test results
    if last_restore_test_ok is None:
        return "untested"
    if last_restore_test_ok is False:
        return "partial"
    hours = _hours_since(last_restore_tested_at)
    if hours is not None and hours <= 48:
        return "verified"
    return "stale"
