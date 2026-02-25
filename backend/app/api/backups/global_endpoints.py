"""Global backup endpoints (cross-project)."""

from fastapi import APIRouter

from ...storage import backups as backup_store
from .converters import backup_to_response
from .models import BackupListResponse, StorageSummaryResponse

router = APIRouter()


@router.get("/backups", response_model=BackupListResponse)
async def list_all_backups(
    limit: int = 50,
    offset: int = 0,
    status: str | None = None,
    source_id: str | None = None,
) -> BackupListResponse:
    """List all backups across all sources."""
    backups, total = backup_store.list_backups(
        source_id=source_id,
        limit=limit,
        offset=offset,
        status=status,
    )
    return BackupListResponse(
        backups=[backup_to_response(b) for b in backups],
        total=total,
    )


@router.get("/backups/storage", response_model=StorageSummaryResponse)
async def get_storage_summary(
    project_id: str | None = None,
    source_id: str | None = None,
) -> StorageSummaryResponse:
    """Get storage usage summary.

    If source_id or project_id is provided, returns summary for that source/project only.
    Otherwise returns global summary across all sources.
    """
    summary = backup_store.get_storage_summary(project_id=project_id, source_id=source_id)
    return StorageSummaryResponse(
        total_count=summary["total_count"],
        total_bytes=summary["total_bytes"],
        by_status=summary["by_status"],
    )
