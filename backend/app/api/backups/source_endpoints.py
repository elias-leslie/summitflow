"""Backup source endpoints."""

from fastapi import APIRouter, HTTPException

from ...storage import backups as backup_store
from .converters import backup_to_response
from .models import (
    BackupCreate,
    BackupListResponse,
    BackupSourceCreate,
    BackupSourceResponse,
    BackupSourceUpdate,
    RestoreRequest,
    RestoreResponse,
)
from .utils import parse_iso_datetime

router = APIRouter()


def _source_to_response(source: dict[str, object]) -> BackupSourceResponse:
    """Convert source dict to response model."""
    return BackupSourceResponse(
        id=str(source["id"]),
        name=str(source["name"]),
        path=str(source["path"]),
        source_type=str(source["source_type"]),
        project_id=str(source["project_id"]) if source.get("project_id") else None,
        enabled=bool(source["enabled"]),
        frequency=str(source["frequency"]),
        retention_days=int(str(source["retention_days"])),
        last_run_at=parse_iso_datetime(source.get("last_run_at")),
        next_run_at=parse_iso_datetime(source.get("next_run_at")),
        created_at=parse_iso_datetime(source.get("created_at")),
        updated_at=parse_iso_datetime(source.get("updated_at")),
    )


@router.get("/backup-sources", response_model=list[BackupSourceResponse])
async def list_backup_sources(
    source_type: str | None = None,
) -> list[BackupSourceResponse]:
    """List all backup sources, optionally filtered by type."""
    sources = backup_store.list_sources(source_type=source_type)
    return [_source_to_response(s) for s in sources]


@router.get("/backup-sources/{source_id}", response_model=BackupSourceResponse)
async def get_backup_source(
    source_id: str,
    project_id: str | None = None,
) -> BackupSourceResponse:
    """Get a backup source by ID."""
    source = backup_store.get_source(source_id)
    if not source:
        raise HTTPException(status_code=404, detail=f"Source {source_id} not found")
    if project_id and str(source.get("project_id", "")) != project_id:
        raise HTTPException(status_code=404, detail=f"Source {source_id} not found")
    return _source_to_response(source)


@router.post("/backup-sources", response_model=BackupSourceResponse, status_code=201)
async def create_backup_source(request: BackupSourceCreate) -> BackupSourceResponse:
    """Register a new backup source."""
    source = backup_store.create_source(
        source_id=request.id,
        name=request.name,
        path=request.path,
        source_type=request.source_type,
        project_id=request.project_id,
    )
    return _source_to_response(source)


@router.put("/backup-sources/{source_id}", response_model=BackupSourceResponse)
async def update_backup_source(
    source_id: str,
    request: BackupSourceUpdate,
    project_id: str | None = None,
) -> BackupSourceResponse:
    """Update a backup source (name, schedule config)."""
    existing = backup_store.get_source(source_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Source {source_id} not found")
    if project_id and str(existing.get("project_id", "")) != project_id:
        raise HTTPException(status_code=404, detail=f"Source {source_id} not found")

    fields = request.model_dump(exclude_unset=True)
    if fields.get("frequency") and fields["frequency"] not in ("daily", "weekly", "monthly"):
        raise HTTPException(
            status_code=400,
            detail="frequency must be 'daily', 'weekly', or 'monthly'",
        )

    updated = backup_store.update_source(source_id, **fields)
    if not updated:
        raise HTTPException(status_code=404, detail=f"Source {source_id} not found")
    return _source_to_response(updated)


@router.delete("/backup-sources/{source_id}")
async def delete_backup_source(
    source_id: str,
    project_id: str | None = None,
) -> dict[str, object]:
    """Delete a backup source."""
    source = backup_store.get_source(source_id)
    if not source:
        raise HTTPException(status_code=404, detail=f"Source {source_id} not found")
    if project_id and str(source.get("project_id", "")) != project_id:
        raise HTTPException(status_code=404, detail=f"Source {source_id} not found")
    deleted = backup_store.delete_source(source_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Source {source_id} not found")
    return {"deleted": True, "source_id": source_id}


@router.post("/backup-sources/{source_id}/backups", response_model=RestoreResponse)
async def create_source_backup(
    source_id: str,
    request: BackupCreate,
) -> RestoreResponse:
    """Create a backup for a specific source."""
    source = backup_store.get_source(source_id)
    if not source:
        raise HTTPException(status_code=404, detail=f"Source {source_id} not found")

    from ...workflows.models import BackupInput
    from ...workflows.utility import backup_create_wf

    await backup_create_wf.aio_run_no_wait(
        BackupInput(
            project_id=str(source.get("project_id") or source_id),
            source_id=source_id,
            note=request.note,
            backup_type="manual",
            keep_local=request.keep_local,
        )
    )
    return RestoreResponse(
        status="queued",
        message=f"Backup task queued for source {source_id}",
    )


@router.post(
    "/backup-sources/{source_id}/backups/{backup_id}/restore",
    response_model=RestoreResponse,
)
async def restore_source_backup(
    source_id: str,
    backup_id: str,
    request: RestoreRequest,
) -> RestoreResponse:
    """Restore from a backup for a specific source."""
    source = backup_store.get_source(source_id)
    if not source:
        raise HTTPException(status_code=404, detail=f"Source {source_id} not found")

    backup = backup_store.get_backup(backup_id)
    if not backup:
        raise HTTPException(status_code=404, detail=f"Backup {backup_id} not found")
    if backup["source_id"] != source_id:
        raise HTTPException(
            status_code=404,
            detail=f"Backup {backup_id} not found in source {source_id}",
        )

    from ...workflows.models import RestoreInput
    from ...workflows.utility import backup_restore_wf

    await backup_restore_wf.aio_run_no_wait(
        RestoreInput(
            project_id=str(source.get("project_id") or source_id),
            source_id=source_id,
            backup_id=backup_id,
            dry_run=request.dry_run,
            db_only=request.db_only,
            files_only=request.files_only,
        )
    )
    return RestoreResponse(
        status="queued",
        message=f"Restore task queued for backup {backup_id} (source {source_id})",
    )


@router.get("/backup-sources/{source_id}/backups", response_model=BackupListResponse)
async def list_source_backups(
    source_id: str,
    limit: int = 50,
    offset: int = 0,
    status: str | None = None,
) -> BackupListResponse:
    """List backups for a specific source."""
    source = backup_store.get_source(source_id)
    if not source:
        raise HTTPException(status_code=404, detail=f"Source {source_id} not found")

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
