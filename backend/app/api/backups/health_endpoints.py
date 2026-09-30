"""Backup health monitoring endpoints."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC

from fastapi import APIRouter

from ...logging_config import get_logger
from ...storage import backups as backup_store
from ...tasks.backup_coverage import get_coverage_summary, verify_archive_coverage
from ...tasks.backup_lock import has_active_backup_lease
from ...tasks.backup_utils import REPOSITORY_CRITICAL_RESTORE_DAYS, build_storage_env
from .models import (
    BackupHealthItem,
    BackupHealthResponse,
    CoverageResponse,
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
        verification = row.get("latest_verification_json")
        verification = verification if isinstance(verification, Mapping) else {}
        coverage_complete = (
            verify_archive_coverage(dict(verification)).complete
            if source_type == "infrastructure"
            else None
        )
        offsite = verification.get("offsite")
        offsite = offsite if isinstance(offsite, Mapping) else {}
        isolated_restore = verification.get("isolated_restore")
        isolated_restore = isolated_restore if isinstance(isolated_restore, Mapping) else {}
        storage_env = build_storage_env(str(row["source_id"]))
        offsite_configured = bool(storage_env.get("BACKUP_OFFSITE_GIO_URI"))
        offsite_status = str(offsite.get("status") or ("pending" if offsite_configured and last_success else "unconfigured"))
        raw_activity = row.get("backup_activity")
        activity = dict(raw_activity) if isinstance(raw_activity, Mapping) else None
        if activity and activity.get("active") is True:
            try:
                if not has_active_backup_lease(str(row["source_id"])):
                    activity.update(active=False, phase="failed", attention=True, remote_outcome_unknown=True)
            except Exception:
                # Loss of the coordination service is unknown, not proof that
                # another attempt can safely be started.
                activity["attention"] = True

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
            drill_freshness_hours=REPOSITORY_CRITICAL_RESTORE_DAYS * 24
            if storage_env.get("BACKUP_ENGINE") == "restic" and storage_env.get("RESTIC_REMOTE_REPOSITORY")
            else 48,
        )

        # Infrastructure combines current archive checks with dated drill evidence.
        # - red: most recent backup failed OR (infra: drill failed)
        # - yellow: pending upload, missing coverage, or stale/untested drill evidence
        # - green: current archive checks pass AND a recent recorded drill succeeded
        if not row["enabled"]:
            health_status = "disabled"
        elif last_status == "failed" or offsite_status == "failed" or (
            source_type == "infrastructure" and last_drill_ok is False
        ):
            health_status = "red"
        elif last_status == "completed_pending_upload" or offsite_status in {
            "pending",
            "unconfigured",
        }:
            health_status = "yellow"
        elif source_type == "infrastructure":
            # A new capture does not invalidate a demonstrated restore process.
            # Return the tested backup ID/date separately; this is not a claim
            # that the newest recovery point itself passed a restore drill.
            if (
                last_success
                and last_drill_ok is True
                and restore_confidence == "verified"
                and last_drill_at is not None
                and last_drill_backup_id is not None
                and coverage_complete is True
                and row.get("latest_backup_id") is not None
            ):
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
                coverage_complete=coverage_complete,
                last_drill_at=last_drill_at,
                last_drill_ok=last_drill_ok,
                last_drill_backup_id=last_drill_backup_id,
                latest_backup_id=row.get("latest_backup_id"),
                offsite_status=offsite_status,
                last_offsite_verified_at=_mapping_str(offsite, "verified_at"),
                offsite_location=_mapping_str(offsite, "location"),
                offsite_checksum=_mapping_str(offsite, "checksum"),
                offsite_error=_mapping_str(offsite, "error") if offsite_status == "failed" else None,
                last_isolated_restore_at=_mapping_str(isolated_restore, "verified_at"),
                last_isolated_restore_ok=_mapping_bool(isolated_restore, "ok"),
                backup_activity=activity,
            )
        )

    return BackupHealthResponse(
        sources=items,
        pending_upload_count=total_pending_upload,
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


def _mapping_str(data: Mapping[object, object], key: str) -> str | None:
    value = data.get(key)
    return str(value) if value is not None else None


def _mapping_bool(data: Mapping[object, object], key: str) -> bool | None:
    value = data.get(key)
    return value if isinstance(value, bool) else None


def _compute_restore_confidence(
    *,
    source_type: str,
    last_drill_at: str | None,
    last_drill_ok: bool | None,
    last_restore_test_ok: bool | None,
    last_restore_tested_at: str | None,
    drill_freshness_hours: int = 48,
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
        # Match the effective backend's drill cadence, retaining dated evidence.
        hours = _hours_since(last_drill_at)
        if hours is not None and hours <= drill_freshness_hours:
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
