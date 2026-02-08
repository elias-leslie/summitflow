"""Backup Management API - Create, list, and restore backups."""

import asyncio
from datetime import datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from ..logging_config import get_logger
from ..storage import backups as backup_store
from ..tasks.backup import create_backup, restore_backup

router = APIRouter()

logger = get_logger(__name__)


class BackupCreate(BaseModel):
    """Request model for creating a backup."""

    note: str | None = None
    keep_local: bool = False


class BackupResponse(BaseModel):
    """Response model for a backup."""

    id: str
    project_id: str
    name: str
    backup_type: str
    status: str
    size_bytes: int | None = None
    db_size_bytes: int | None = None
    files_size_bytes: int | None = None
    location: str | None = None
    note: str | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None


class BackupListResponse(BaseModel):
    """Response model for listing backups."""

    backups: list[BackupResponse]
    total: int


class RestoreRequest(BaseModel):
    """Request model for restore operation."""

    dry_run: bool = False
    db_only: bool = False
    files_only: bool = False


class RestoreResponse(BaseModel):
    """Response model for restore operation."""

    task_id: str
    status: str
    message: str


class ScheduleRequest(BaseModel):
    """Request model for backup schedule."""

    enabled: bool
    frequency: str  # 'daily', 'weekly', 'monthly'
    retention_count: int = 5


class ScheduleResponse(BaseModel):
    """Response model for backup schedule."""

    id: int
    project_id: str
    enabled: bool
    frequency: str
    retention_count: int
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class StorageSummaryResponse(BaseModel):
    """Response model for storage usage summary."""

    total_count: int
    total_bytes: int
    by_status: dict[str, int]


def _backup_to_response(backup: dict[str, Any]) -> BackupResponse:
    """Convert backup dict to response model."""
    return BackupResponse(
        id=str(backup["id"]),
        project_id=str(backup["project_id"]),
        name=str(backup["name"]),
        backup_type=str(backup["backup_type"]),
        status=str(backup["status"]),
        size_bytes=backup.get("size_bytes"),
        db_size_bytes=backup.get("db_size_bytes"),
        files_size_bytes=backup.get("files_size_bytes"),
        location=backup.get("location"),
        note=backup.get("note"),
        created_at=datetime.fromisoformat(backup["created_at"])
        if backup.get("created_at")
        else None,
        started_at=datetime.fromisoformat(backup["started_at"])
        if backup.get("started_at")
        else None,
        completed_at=datetime.fromisoformat(backup["completed_at"])
        if backup.get("completed_at")
        else None,
        error_message=backup.get("error_message"),
    )


# ============================================================
# Project-scoped endpoints
# ============================================================


@router.get("/projects/{project_id}/backups", response_model=BackupListResponse)
async def list_project_backups(
    project_id: str,
    limit: int = 50,
    offset: int = 0,
    status: str | None = None,
) -> BackupListResponse:
    """List backups for a project."""
    backups, total = backup_store.list_backups(
        project_id=project_id,
        limit=limit,
        offset=offset,
        status=status,
    )
    return BackupListResponse(
        backups=[_backup_to_response(b) for b in backups],
        total=total,
    )


@router.post("/projects/{project_id}/backups", response_model=RestoreResponse)
async def create_project_backup(
    project_id: str,
    request: BackupCreate,
    background_tasks: BackgroundTasks,
) -> RestoreResponse:
    """Create a new backup for a project (async).

    Returns task_id that can be used to track progress.
    """
    task = create_backup.delay(
        project_id=project_id,
        note=request.note,
        backup_type="manual",
        keep_local=request.keep_local,
    )
    return RestoreResponse(
        task_id=task.id,
        status="queued",
        message=f"Backup task queued for project {project_id}",
    )


# Schedule endpoints MUST be before {backup_id} routes to avoid "schedule" matching as backup_id
@router.get("/projects/{project_id}/backups/schedule", response_model=ScheduleResponse | None)
async def get_backup_schedule(project_id: str) -> ScheduleResponse | None:
    """Get backup schedule for a project."""
    schedule = backup_store.get_schedule(project_id)
    if not schedule:
        return None
    return ScheduleResponse(
        id=schedule["id"],
        project_id=schedule["project_id"],
        enabled=schedule["enabled"],
        frequency=schedule["frequency"],
        retention_count=schedule["retention_count"],
        last_run_at=datetime.fromisoformat(schedule["last_run_at"])
        if schedule.get("last_run_at")
        else None,
        next_run_at=datetime.fromisoformat(schedule["next_run_at"])
        if schedule.get("next_run_at")
        else None,
        created_at=datetime.fromisoformat(schedule["created_at"])
        if schedule.get("created_at")
        else None,
        updated_at=datetime.fromisoformat(schedule["updated_at"])
        if schedule.get("updated_at")
        else None,
    )


@router.put("/projects/{project_id}/backups/schedule", response_model=ScheduleResponse)
async def update_backup_schedule(project_id: str, request: ScheduleRequest) -> ScheduleResponse:
    """Create or update backup schedule for a project."""
    if request.frequency not in ("daily", "weekly", "monthly"):
        raise HTTPException(
            status_code=400, detail="frequency must be 'daily', 'weekly', or 'monthly'"
        )

    schedule = backup_store.upsert_schedule(
        project_id=project_id,
        enabled=request.enabled,
        frequency=request.frequency,
        retention_count=request.retention_count,
    )
    return ScheduleResponse(
        id=schedule["id"],
        project_id=schedule["project_id"],
        enabled=schedule["enabled"],
        frequency=schedule["frequency"],
        retention_count=schedule["retention_count"],
        last_run_at=datetime.fromisoformat(schedule["last_run_at"])
        if schedule.get("last_run_at")
        else None,
        next_run_at=datetime.fromisoformat(schedule["next_run_at"])
        if schedule.get("next_run_at")
        else None,
        created_at=datetime.fromisoformat(schedule["created_at"])
        if schedule.get("created_at")
        else None,
        updated_at=datetime.fromisoformat(schedule["updated_at"])
        if schedule.get("updated_at")
        else None,
    )


@router.get("/projects/{project_id}/backups/{backup_id}", response_model=BackupResponse)
async def get_backup(project_id: str, backup_id: str) -> BackupResponse:
    """Get details of a specific backup."""
    backup = backup_store.get_backup(backup_id)
    if not backup:
        raise HTTPException(status_code=404, detail=f"Backup {backup_id} not found")
    if backup["project_id"] != project_id:
        raise HTTPException(
            status_code=404, detail=f"Backup {backup_id} not found in project {project_id}"
        )
    return _backup_to_response(backup)


@router.post("/projects/{project_id}/backups/{backup_id}/restore", response_model=RestoreResponse)
async def restore_project_backup(
    project_id: str,
    backup_id: str,
    request: RestoreRequest,
    background_tasks: BackgroundTasks,
) -> RestoreResponse:
    """Restore from a backup (async).

    Returns task_id that can be used to track progress.
    """
    backup = backup_store.get_backup(backup_id)
    if not backup:
        raise HTTPException(status_code=404, detail=f"Backup {backup_id} not found")
    if backup["project_id"] != project_id:
        raise HTTPException(
            status_code=404, detail=f"Backup {backup_id} not found in project {project_id}"
        )

    task = restore_backup.delay(
        project_id=project_id,
        backup_id=backup_id,
        dry_run=request.dry_run,
        db_only=request.db_only,
        files_only=request.files_only,
    )
    return RestoreResponse(
        task_id=task.id,
        status="queued",
        message=f"Restore task queued for backup {backup_id}",
    )


@router.get("/projects/{project_id}/backups/{backup_id}/restore/preview")
async def preview_restore(project_id: str, backup_id: str) -> dict[str, Any]:
    """Preview what would be restored (dry-run).

    Runs restore with dry_run=True synchronously.
    """
    backup = backup_store.get_backup(backup_id)
    if not backup:
        raise HTTPException(status_code=404, detail=f"Backup {backup_id} not found")
    if backup["project_id"] != project_id:
        raise HTTPException(
            status_code=404, detail=f"Backup {backup_id} not found in project {project_id}"
        )

    # Run dry-run in a thread to avoid blocking the async event loop
    result = await asyncio.to_thread(
        restore_backup,
        project_id=project_id,
        backup_id=backup_id,
        dry_run=True,
    )
    return {
        "backup_id": backup_id,
        "backup_name": backup["name"],
        "dry_run": True,
        "result": result,
    }


@router.delete("/projects/{project_id}/backups/{backup_id}")
async def delete_backup(project_id: str, backup_id: str) -> dict[str, Any]:
    """Delete a backup record.

    Note: This only deletes the record, not the actual backup files.
    """
    backup = backup_store.get_backup(backup_id)
    if not backup:
        raise HTTPException(status_code=404, detail=f"Backup {backup_id} not found")
    if backup["project_id"] != project_id:
        raise HTTPException(
            status_code=404, detail=f"Backup {backup_id} not found in project {project_id}"
        )

    location = backup.get("location")
    backup_name = backup.get("name")

    deleted = backup_store.delete_backup_record(backup_id)
    if not deleted:
        raise HTTPException(status_code=500, detail="Failed to delete backup")

    if location and location != "pending_upload":
        logger.info(
            "backup_record_deleted_files_remain",
            backup_id=backup_id,
            backup_name=backup_name,
            location=location,
        )

    return {"deleted": True, "backup_id": backup_id}


# ============================================================
# Global endpoints
# ============================================================


@router.get("/backups", response_model=BackupListResponse)
async def list_all_backups(
    limit: int = 50,
    offset: int = 0,
    status: str | None = None,
) -> BackupListResponse:
    """List all backups across all projects."""
    backups, total = backup_store.list_backups(
        project_id=None,
        limit=limit,
        offset=offset,
        status=status,
    )
    return BackupListResponse(
        backups=[_backup_to_response(b) for b in backups],
        total=total,
    )


@router.get("/backups/storage", response_model=StorageSummaryResponse)
async def get_storage_summary(project_id: str | None = None) -> StorageSummaryResponse:
    """Get storage usage summary.

    If project_id is provided, returns summary for that project only.
    Otherwise returns global summary across all projects.
    """
    summary = backup_store.get_storage_summary(project_id)
    return StorageSummaryResponse(
        total_count=summary["total_count"],
        total_bytes=summary["total_bytes"],
        by_status=summary["by_status"],
    )
