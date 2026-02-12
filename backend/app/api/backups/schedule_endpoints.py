"""Backup schedule endpoints."""

from fastapi import APIRouter, HTTPException

from ...storage import backups as backup_store
from .models import ScheduleRequest, ScheduleResponse
from .utils import parse_iso_datetime

router = APIRouter()


@router.get(
    "/projects/{project_id}/backups/schedule",
    response_model=ScheduleResponse | None,
)
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
        retention_days=schedule["retention_days"],
        last_run_at=parse_iso_datetime(schedule.get("last_run_at")),
        next_run_at=parse_iso_datetime(schedule.get("next_run_at")),
        created_at=parse_iso_datetime(schedule.get("created_at")),
        updated_at=parse_iso_datetime(schedule.get("updated_at")),
    )


@router.put("/projects/{project_id}/backups/schedule", response_model=ScheduleResponse)
async def update_backup_schedule(
    project_id: str,
    request: ScheduleRequest,
) -> ScheduleResponse:
    """Create or update backup schedule for a project."""
    if request.frequency not in ("daily", "weekly", "monthly"):
        raise HTTPException(
            status_code=400,
            detail="frequency must be 'daily', 'weekly', or 'monthly'",
        )

    schedule = backup_store.upsert_schedule(
        project_id=project_id,
        enabled=request.enabled,
        frequency=request.frequency,
        retention_days=request.retention_days,
    )
    return ScheduleResponse(
        id=schedule["id"],
        project_id=schedule["project_id"],
        enabled=schedule["enabled"],
        frequency=schedule["frequency"],
        retention_days=schedule["retention_days"],
        last_run_at=parse_iso_datetime(schedule.get("last_run_at")),
        next_run_at=parse_iso_datetime(schedule.get("next_run_at")),
        created_at=parse_iso_datetime(schedule.get("created_at")),
        updated_at=parse_iso_datetime(schedule.get("updated_at")),
    )
