"""System health and resource monitoring endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..services.resource_monitor import (
    get_cpu_usage,
    get_disk_usage,
    get_memory_usage,
)
from ..storage import maintenance_runs as maintenance_store

router = APIRouter(prefix="/api/system", tags=["system"])

MONITORED_MAINTENANCE_WORKFLOWS = ("daily_maintenance", "scheduled_backups")


class DiskUsageResponse(BaseModel):
    """Disk usage information."""

    total_gb: float
    used_gb: float
    free_gb: float
    percent_used: float
    status: str


class MemoryUsageResponse(BaseModel):
    """Memory usage information."""

    total_gb: float
    used_gb: float
    available_gb: float
    percent_used: float
    status: str


class CpuUsageResponse(BaseModel):
    """CPU usage information."""

    percent_used: float
    cores: int
    status: str


class ResourcesResponse(BaseModel):
    """System resources response."""

    disk: DiskUsageResponse
    memory: MemoryUsageResponse
    cpu: CpuUsageResponse
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="Response timestamp"
    )


class MaintenanceRunResponse(BaseModel):
    """One recorded maintenance workflow run."""

    id: int
    workflow_name: str
    status: str
    started_at: datetime
    finished_at: datetime | None = None
    duration_ms: int | None = None
    rows_cleaned: int
    summary: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None
    created_at: datetime


class MaintenanceStatusResponse(BaseModel):
    """Operator-facing maintenance run overview."""

    latest: dict[str, MaintenanceRunResponse] = Field(default_factory=dict)
    recent: list[MaintenanceRunResponse] = Field(default_factory=list)


@router.get("/stats", response_model=ResourcesResponse)
def get_system_resources() -> ResourcesResponse:
    """Get current system resource usage (disk, memory, CPU).

    Returns:
        ResourcesResponse: System resource statistics with thresholds
    """
    try:
        # Get resource statistics
        disk = get_disk_usage()
        memory = get_memory_usage()
        cpu = get_cpu_usage()

        # Ensure cores is not None (default to 1 if psutil.cpu_count() returns None)
        cpu_cores = cpu["cores"] if cpu["cores"] is not None else 1

        return ResourcesResponse(
            disk=DiskUsageResponse(**disk),
            memory=MemoryUsageResponse(**memory),
            cpu=CpuUsageResponse(
                percent_used=cpu["percent_used"],
                cores=cpu_cores,
                status=cpu["status"],
            ),
        )

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error retrieving system resources: {e!s}"
        ) from e


@router.get("/maintenance", response_model=MaintenanceStatusResponse)
def get_maintenance_status(
    limit: int = Query(default=10, ge=1, le=50),
) -> MaintenanceStatusResponse:
    """Return recent maintenance workflow runs and the latest run per workflow."""
    latest = {
        workflow_name: MaintenanceRunResponse(**run)
        for workflow_name, run in maintenance_store.get_latest_maintenance_runs(
            MONITORED_MAINTENANCE_WORKFLOWS
        ).items()
    }
    recent = [
        MaintenanceRunResponse(**run)
        for run in maintenance_store.list_maintenance_runs(limit=limit)
    ]
    return MaintenanceStatusResponse(latest=latest, recent=recent)
