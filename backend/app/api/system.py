"""System health and resource monitoring endpoints."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..services.resource_monitor import (
    get_cpu_usage,
    get_disk_usage,
    get_memory_usage,
)

router = APIRouter(prefix="/api/system", tags=["system"])


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
