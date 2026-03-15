"""Backup health monitoring endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from ...storage import backups as backup_store
from .models import BackupHealthItem, BackupHealthResponse

router = APIRouter()


@router.get("/backups/health", response_model=BackupHealthResponse)
async def backup_health() -> BackupHealthResponse:
    """Per-source backup health: last success, next run, failure count (7d)."""
    rows = backup_store.get_backup_health_summary()
    items = []
    for row in rows:
        failure_count = row.get("failure_count_7d", 0)
        last_success = row.get("last_success_at")
        last_status = row.get("last_backup_status")

        # Health logic:
        # - red: most recent backup failed (active problem needing attention)
        # - yellow: never had a successful backup, or no backups at all
        # - green: most recent backup succeeded (past failures don't matter)
        if last_status == "failed":
            health_status = "red"
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
            )
        )

    return BackupHealthResponse(sources=items)
