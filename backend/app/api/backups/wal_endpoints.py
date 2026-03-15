"""WAL archiving management endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ...tasks.backup_wal import disable_wal_archiving, enable_wal_archiving, get_wal_status
from ...tasks.backup_wal_cleanup import cleanup_wal_archive, get_wal_archive_info

router = APIRouter()


@router.get("/backups/wal/status")
async def wal_status() -> dict:
    """Get current WAL archiving status."""
    return get_wal_status()


@router.get("/backups/wal/archive")
async def wal_archive() -> dict:
    """Get WAL archive directory inventory."""
    return get_wal_archive_info()


@router.post("/backups/wal/cleanup")
async def wal_cleanup(dry_run: bool = False, retention_days: int = 7) -> dict:
    """Clean up old WAL segments past retention."""
    return cleanup_wal_archive(retention_days=retention_days, dry_run=dry_run)


@router.post("/backups/wal/enable")
async def wal_enable() -> dict:
    """Enable WAL archiving."""
    try:
        return enable_wal_archiving()
    except Exception as exc:
        msg = str(exc)
        if "permission denied" in msg:
            raise HTTPException(
                status_code=403,
                detail="Database user lacks superuser privileges required for ALTER SYSTEM. "
                "Configure DATABASE_ADMIN_URL with a superuser connection.",
            ) from exc
        raise HTTPException(status_code=500, detail=msg) from exc


@router.post("/backups/wal/disable")
async def wal_disable() -> dict:
    """Disable WAL archiving."""
    try:
        return disable_wal_archiving()
    except Exception as exc:
        msg = str(exc)
        if "permission denied" in msg:
            raise HTTPException(
                status_code=403,
                detail="Database user lacks superuser privileges required for ALTER SYSTEM. "
                "Configure DATABASE_ADMIN_URL with a superuser connection.",
            ) from exc
        raise HTTPException(status_code=500, detail=msg) from exc
