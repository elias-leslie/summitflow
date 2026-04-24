"""Project-scoped backup endpoints."""

import asyncio

from fastapi import APIRouter, BackgroundTasks, HTTPException

from ...logging_config import get_logger
from ...storage import backups as backup_store
from ...tasks.backup import restore_backup
from .converters import backup_to_response
from .models import (
    BackupCreate,
    BackupListResponse,
    BackupResponse,
    RestoreRequest,
    RestoreResponse,
)
from .utils import validate_backup_access

router = APIRouter()

logger = get_logger(__name__)


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
        backups=[backup_to_response(b) for b in backups],
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
    from ...workflows.models import BackupInput
    from ...workflows.utility import backup_create_wf

    workflow_run = await backup_create_wf.aio_run_no_wait(
        BackupInput(
            project_id=project_id,
            source_id=project_id,
            note=request.note,
            backup_type="manual",
            keep_local=request.keep_local,
        )
    )
    return RestoreResponse(
        task_id=workflow_run.workflow_run_id,
        status="queued",
        message=f"Backup task queued for project {project_id}",
    )


@router.get("/projects/{project_id}/backups/{backup_id}", response_model=BackupResponse)
async def get_backup(project_id: str, backup_id: str) -> BackupResponse:
    """Get details of a specific backup."""
    backup = validate_backup_access(project_id, backup_id)
    return backup_to_response(backup)


@router.post(
    "/projects/{project_id}/backups/{backup_id}/restore",
    response_model=RestoreResponse,
)
async def restore_project_backup(
    project_id: str,
    backup_id: str,
    request: RestoreRequest,
    background_tasks: BackgroundTasks,
) -> RestoreResponse:
    """Restore from a backup asynchronously."""
    validate_backup_access(project_id, backup_id)

    from ...workflows.models import RestoreInput
    from ...workflows.utility import backup_restore_wf

    await backup_restore_wf.aio_run_no_wait(
        RestoreInput(
            project_id=project_id,
            backup_id=backup_id,
            dry_run=request.dry_run,
            db_only=request.db_only,
            files_only=request.files_only,
        )
    )
    return RestoreResponse(
        status="queued",
        message=f"Restore task queued for backup {backup_id}",
    )


@router.get("/projects/{project_id}/backups/{backup_id}/restore/preview")
async def preview_restore(project_id: str, backup_id: str) -> dict[str, object]:
    """Preview what would be restored (dry-run)."""
    backup = validate_backup_access(project_id, backup_id)

    # Run dry-run in thread to avoid blocking event loop
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
async def delete_backup(project_id: str, backup_id: str) -> dict[str, object]:
    """Delete a backup record (does not delete files)."""
    backup = validate_backup_access(project_id, backup_id)

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
