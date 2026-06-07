"""System resource monitoring service.

Provides functions to monitor:
- Disk usage
- Memory usage
- CPU usage
- Database connection pool statistics
"""

import os
import shutil
import subprocess
from typing import TypedDict

import psutil

from ..utils import safe_subprocess

MONITORED_DISK_PATHS = tuple(path for path in ("/", os.environ.get("ST_WORKSPACES_ROOT", "")) if path)

# nvidia-smi can occasionally block on a wedged driver; bound every call.
_NVIDIA_SMI_TIMEOUT_SECONDS = 4.0
DISK_LABELS = {"/": "Root"}
if os.environ.get("ST_WORKSPACES_ROOT"):
    DISK_LABELS[os.environ["ST_WORKSPACES_ROOT"]] = "Workspaces"


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


class GPUProcessDict(TypedDict):
    """A single process holding GPU memory."""

    pid: int
    name: str
    command: str | None
    used_mb: int | None
    type: str  # "compute" | "display"


class GPUDeviceDict(TypedDict):
    """Per-device GPU utilization and memory."""

    index: int
    name: str
    utilization_percent: float | None
    memory_total_mb: int
    memory_used_mb: int
    memory_free_mb: int
    memory_percent_used: float
    temperature_c: float | None
    power_draw_w: float | None
    power_limit_w: float | None
    status: str
    processes: list[GPUProcessDict]


class GPUStatusDict(TypedDict):
    """GPU status across all devices, or availability/error info."""

    available: bool
    error: str | None
    devices: list[GPUDeviceDict]


def _run_nvidia_smi(query: str) -> list[list[str]]:
    """Run an nvidia-smi CSV query and return rows of trimmed string fields."""
    result = safe_subprocess.run(
        ["nvidia-smi", query, "--format=csv,noheader,nounits"],
        capture_output=True,
        text=True,
        timeout=_NVIDIA_SMI_TIMEOUT_SECONDS,
        check=True,
    )
    rows: list[list[str]] = []
    for line in result.stdout.strip().splitlines():
        if line.strip():
            rows.append([cell.strip() for cell in line.split(",")])
    return rows


def _to_float(value: str) -> float | None:
    try:
        return round(float(value), 1)
    except (ValueError, TypeError):
        return None


def _to_int(value: str) -> int | None:
    parsed = _to_float(value)
    return int(parsed) if parsed is not None else None


def _process_command(pid: int) -> str | None:
    """Best-effort short command line for a PID, for GPU-usage attribution."""
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as handle:
            raw = handle.read()
    except OSError:
        return None
    command = raw.replace(b"\x00", b" ").decode(errors="replace").strip()
    if not command:
        return None
    return command if len(command) <= 120 else f"{command[:117]}..."


def _gpu_compute_processes() -> list[GPUProcessDict]:
    """List CUDA/compute processes holding GPU memory (the offloadable ones)."""
    try:
        rows = _run_nvidia_smi(
            "--query-compute-apps=pid,process_name,used_gpu_memory",
        )
    except (OSError, subprocess.SubprocessError):
        return []
    processes: list[GPUProcessDict] = []
    for row in rows:
        if len(row) < 3:
            continue
        pid = _to_int(row[0])
        if pid is None:
            continue
        processes.append(
            {
                "pid": pid,
                "name": os.path.basename(row[1]) or row[1],
                "command": _process_command(pid),
                "used_mb": _to_int(row[2]),
                "type": "compute",
            }
        )
    return processes


def _gpu_status_from_memory(percent_used: float) -> str:
    if percent_used >= 90:
        return "critical"
    if percent_used >= 75:
        return "warning"
    return "ok"


def get_gpu_usage() -> GPUStatusDict:
    """Get NVIDIA GPU utilization, memory, and the processes using each device.

    Returns available=False (never raises) when no NVIDIA GPU/driver is present,
    so callers can render a graceful "no GPU" state. The process list pairs
    compute apps with a synthetic "display/desktop" row accounting for the
    remaining VRAM, so operators can see what to offload before loading a model.
    """
    if shutil.which("nvidia-smi") is None:
        return {"available": False, "error": "nvidia-smi not found", "devices": []}

    try:
        device_rows = _run_nvidia_smi(
            "--query-gpu=index,name,utilization.gpu,memory.total,memory.used,"
            "memory.free,temperature.gpu,power.draw,power.limit",
        )
    except subprocess.TimeoutExpired:
        return {"available": False, "error": "nvidia-smi timed out", "devices": []}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"available": False, "error": str(exc), "devices": []}

    compute_processes = _gpu_compute_processes()
    devices: list[GPUDeviceDict] = []
    for row in device_rows:
        if len(row) < 9:
            continue
        index = _to_int(row[0]) or 0
        total = _to_int(row[3]) or 0
        used = _to_int(row[4]) or 0
        free = _to_int(row[5]) or max(total - used, 0)
        percent_used = round((used / total) * 100, 2) if total else 0.0

        # Single-GPU host: attribute all compute procs to this device. The
        # remainder (used - compute) is the display/desktop (Xorg, Chrome...).
        device_processes = list(compute_processes)
        compute_total = sum(p["used_mb"] or 0 for p in device_processes)
        display_mb = used - compute_total
        if display_mb >= 64:
            device_processes.append(
                {
                    "pid": 0,
                    "name": "display & desktop",
                    "command": "Xorg / compositor / browsers (graphics)",
                    "used_mb": display_mb,
                    "type": "display",
                }
            )
        device_processes.sort(key=lambda p: p["used_mb"] or 0, reverse=True)

        devices.append(
            {
                "index": index,
                "name": row[1],
                "utilization_percent": _to_float(row[2]),
                "memory_total_mb": total,
                "memory_used_mb": used,
                "memory_free_mb": free,
                "memory_percent_used": percent_used,
                "temperature_c": _to_float(row[6]),
                "power_draw_w": _to_float(row[7]),
                "power_limit_w": _to_float(row[8]),
                "status": _gpu_status_from_memory(percent_used),
                "processes": device_processes,
            }
        )

    return {"available": True, "error": None, "devices": devices}


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
