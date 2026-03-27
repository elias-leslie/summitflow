"""System resource monitoring service.

Provides functions to monitor:
- Disk usage
- Memory usage
- CPU usage
- Database connection pool statistics
"""

import os
import shutil
from typing import TypedDict

import psutil

MONITORED_DISK_PATHS = ("/", "/srv/workspaces")
DISK_LABELS = {
    "/": "Root",
    "/srv/workspaces": "Workspaces",
}


class DiskUsageDict(TypedDict):
    """Disk usage statistics."""

    label: str
    mount_path: str
    total_gb: float
    used_gb: float
    free_gb: float
    percent_used: float
    status: str


class MemoryUsageDict(TypedDict):
    """Memory usage statistics."""

    total_gb: float
    used_gb: float
    available_gb: float
    percent_used: float
    status: str


class CPUUsageDict(TypedDict):
    """CPU usage statistics."""

    percent_used: float
    cores: int | None
    status: str


def get_disk_usage(path: str = "/") -> DiskUsageDict:
    """Get disk usage statistics for a filesystem mount.

    Returns:
        Dict containing:
            - label: Human-friendly mount label
            - mount_path: Mounted filesystem path
            - total_gb: Total disk space in GB
            - used_gb: Used disk space in GB
            - free_gb: Free disk space in GB
            - percent_used: Percentage of disk space used
            - status: "ok" | "warning" | "critical"
    """
    usage = shutil.disk_usage(path)

    # Convert bytes to GB
    total_gb = usage.total / (1024**3)
    used_gb = usage.used / (1024**3)
    free_gb = usage.free / (1024**3)
    percent_used = (usage.used / usage.total) * 100

    # Determine status based on thresholds
    if percent_used >= 90:
        status = "critical"
    elif percent_used >= 80:
        status = "warning"
    else:
        status = "ok"

    return {
        "label": DISK_LABELS.get(path, path),
        "mount_path": path,
        "total_gb": round(total_gb, 2),
        "used_gb": round(used_gb, 2),
        "free_gb": round(free_gb, 2),
        "percent_used": round(percent_used, 2),
        "status": status,
    }


def get_disk_usages() -> list[DiskUsageDict]:
    """Get disk usage statistics for the monitored mounted filesystems."""
    disks: list[DiskUsageDict] = []
    for path in MONITORED_DISK_PATHS:
        if path != "/" and not os.path.ismount(path):
            continue
        disks.append(get_disk_usage(path))
    return disks


def get_memory_usage() -> MemoryUsageDict:
    """Get memory usage statistics.

    Returns:
        Dict containing:
            - total_gb: Total memory in GB
            - used_gb: Used memory in GB
            - available_gb: Available memory in GB
            - percent_used: Percentage of memory used
            - status: "ok" | "warning" | "critical"
    """
    memory = psutil.virtual_memory()

    # Convert bytes to GB
    total_gb = memory.total / (1024**3)
    used_gb = memory.used / (1024**3)
    available_gb = memory.available / (1024**3)
    percent_used = memory.percent

    # Determine status based on thresholds
    if percent_used >= 95:
        status = "critical"
    elif percent_used >= 85:
        status = "warning"
    else:
        status = "ok"

    return {
        "total_gb": round(total_gb, 2),
        "used_gb": round(used_gb, 2),
        "available_gb": round(available_gb, 2),
        "percent_used": round(percent_used, 2),
        "status": status,
    }


def get_cpu_usage() -> CPUUsageDict:
    """Get CPU usage statistics.

    Returns:
        Dict containing:
            - percent_used: Current CPU usage percentage
            - cores: Number of CPU cores
            - status: "ok" | "warning" | "critical"
    """
    # Get CPU usage (1 second sampling period for more accurate reading)
    percent_used = psutil.cpu_percent(interval=1.0)
    cores = psutil.cpu_count()

    # Determine status based on thresholds
    if percent_used >= 90:
        status = "critical"
    elif percent_used >= 80:
        status = "warning"
    else:
        status = "ok"

    return {
        "percent_used": round(percent_used, 2),
        "cores": cores,
        "status": status,
    }
