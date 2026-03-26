"""Route handlers for the runtime management API."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from .._runtime_proxmox import ProxmoxStatus
from .._runtime_proxmox import get_proxmox_status as _get_proxmox_status
from .constants import BACKUP_DIR
from .helpers import (
    _find_container_name,
    _get_runtime_status,
    _launch_runtime_switch,
    _rebuild_script_path,
    _require_auth,
    _run_docker,
    _run_journalctl_user,
    _runtime_metrics,
    _runtime_service_statuses,
    _sanitize_note,
    _service_action,
    _service_definition,
    _systemctl_user_env,
    _write_runtime_mode,
)
from .models import (
    ActionResult,
    HealthSummary,
    RuntimeModeStatus,
    RuntimeModeUpdate,
    RuntimeServiceMetrics,
    RuntimeServiceStatus,
)

router = APIRouter()


@router.get("/status", response_model=list[RuntimeServiceStatus])
async def get_status() -> list[RuntimeServiceStatus]:
    """Get all managed runtime service statuses."""
    return await _runtime_service_statuses()


@router.get("/runtime", response_model=RuntimeModeStatus)
async def get_runtime_status() -> RuntimeModeStatus:
    """Get the current hybrid runtime mode and Docker parity preference."""
    return await _get_runtime_status()


@router.get("/proxmox", response_model=ProxmoxStatus)
async def get_proxmox_status() -> ProxmoxStatus:
    """Get Proxmox node and guest status for runtime-adjacent infrastructure."""
    return await _get_proxmox_status()


@router.post("/runtime", response_model=ActionResult, dependencies=[Depends(_require_auth)])
async def update_runtime_mode(payload: RuntimeModeUpdate) -> ActionResult:
    """Switch live container mode or save the preferred Docker parity mode."""
    runtime = await _get_runtime_status()
    if runtime.runtime != "docker":
        return _handle_non_docker_mode_update(runtime, payload.mode)

    script_path = _rebuild_script_path()
    if not script_path.exists():
        raise HTTPException(status_code=500, detail="rebuild.sh not found")

    if runtime.current_mode == payload.mode and runtime.is_running:
        return ActionResult(success=True, message=f"Docker stack already running in {payload.mode} mode")

    helper_name = await _launch_runtime_switch(payload.mode, script_path)
    return ActionResult(
        success=True,
        message=f"Queued Docker stack switch to {payload.mode} mode via {helper_name}",
    )


def _handle_non_docker_mode_update(
    runtime: RuntimeModeStatus,
    mode: Literal["dev", "prod"],
) -> ActionResult:
    """Handle runtime mode update when not in full Docker mode."""
    if runtime.configured_mode == mode:
        return ActionResult(
            success=True,
            message=(
                f"Docker parity preference already set to {mode}. "
                "Live services remain native apps with Docker infra."
            ),
        )
    _write_runtime_mode(mode)
    return ActionResult(
        success=True,
        message=(
            f"Saved Docker parity preference: {mode}. "
            "Live services remain native apps with Docker infra."
        ),
    )


@router.get("/metrics", response_model=list[RuntimeServiceMetrics])
async def get_metrics() -> list[RuntimeServiceMetrics]:
    """Get CPU/memory metrics for managed runtime services."""
    return await _runtime_metrics()


@router.get("/logs/{service}", response_model=None, dependencies=[Depends(_require_auth)])
async def get_logs(
    service: str,
    tail: int = Query(default=100, ge=1, le=5000),
    follow: bool = Query(default=False),
) -> StreamingResponse | dict[str, str]:
    """Get service logs. If follow=true, streams via SSE."""
    svc = _service_definition(service)

    if follow:
        return StreamingResponse(
            _stream_logs(svc, tail),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return await _fetch_logs(svc, service, tail)


async def _stream_logs(svc: dict, tail: int):
    """SSE generator for tailing service logs."""
    if svc["manager"] == "systemd":
        proc = await asyncio.create_subprocess_exec(
            "journalctl", "--user", "-u", svc["unit"],
            "-n", str(tail), "-f", "--output=short-iso",
            env=_systemctl_user_env(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    else:
        proc = await asyncio.create_subprocess_exec(
            "docker", "logs", "-f", "--tail", str(tail),
            _find_container_name(svc["container_service"]),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    try:
        while True:
            line = await proc.stdout.readline()  # type: ignore[union-attr]
            if not line:
                break
            yield f"data: {line.decode().rstrip()}\n\n"
    finally:
        proc.terminate()


async def _fetch_logs(svc: dict, service: str, tail: int) -> dict[str, str]:
    """Fetch a fixed number of log lines from a service."""
    if svc["manager"] == "systemd":
        stdout, stderr, rc = await _run_journalctl_user(
            "-u", svc["unit"], "-n", str(tail),
            "--output=short-iso", "--no-pager",
        )
        if rc != 0:
            raise HTTPException(status_code=404, detail=f"Service not found: {service}")
        return {"logs": stdout + stderr}

    stdout, stderr, rc = await _run_docker(
        "docker", "logs", "--tail", str(tail),
        _find_container_name(svc["container_service"]),
    )
    if rc != 0:
        raise HTTPException(status_code=404, detail=f"Service not found: {service}")
    return {"logs": stdout + stderr}


@router.post("/restart/{service}", response_model=ActionResult, dependencies=[Depends(_require_auth)])
async def restart_service(service: str) -> ActionResult:
    """Restart a managed service."""
    return await _service_action(service, "restart")


@router.post("/stop/{service}", response_model=ActionResult, dependencies=[Depends(_require_auth)])
async def stop_service(service: str) -> ActionResult:
    """Stop a managed service."""
    return await _service_action(service, "stop")


@router.post("/start/{service}", response_model=ActionResult, dependencies=[Depends(_require_auth)])
async def start_service(service: str) -> ActionResult:
    """Start a managed service."""
    return await _service_action(service, "start")


@router.post("/backup", response_model=ActionResult, dependencies=[Depends(_require_auth)])
async def create_backup(note: str = "") -> ActionResult:
    """Create an infrastructure backup via the unified backup system."""
    note = _sanitize_note(note)

    try:
        return await _backup_via_workflow(note)
    except Exception as e:
        return await _backup_fallback(note, e)


async def _backup_via_workflow(note: str) -> ActionResult:
    """Attempt backup via the Hatchet workflow system."""
    from ...storage import backups as backup_store

    source = backup_store.get_source("infrastructure")
    if not source:
        backup_store.create_source(
            source_id="infrastructure",
            name="Infrastructure",
            path="/",
            source_type="infrastructure",
        )

    from ...workflows.models import BackupInput
    from ...workflows.utility import backup_create_wf

    await backup_create_wf.aio_run_no_wait(
        BackupInput(
            project_id="infrastructure",
            source_id="infrastructure",
            note=note or None,
            backup_type="manual",
            keep_local=False,
        )
    )
    return ActionResult(
        success=True,
        message="Infrastructure backup queued. Track progress at /backups?source=infrastructure",
    )


async def _backup_fallback(note: str, error: Exception) -> ActionResult:
    """Fallback to direct pg_dumpall when workflow system is unavailable."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    suffix = f"-{note.replace(' ', '-')}" if note else ""
    filename = f"docker-pgdump-{timestamp}{suffix}.sql"
    filepath = BACKUP_DIR / filename

    postgres_container = _find_container_name("postgres")
    stdout, stderr, rc = await _run_docker(
        "docker", "exec", postgres_container, "pg_dumpall", "-U", "admin"
    )
    if rc != 0:
        return ActionResult(success=False, message=f"Backup failed: {stderr}")

    filepath.write_text(stdout)
    size_mb = filepath.stat().st_size / (1024 * 1024)
    return ActionResult(
        success=True, message=f"Backup created: {filename} ({size_mb:.1f} MB) [fallback: {error}]"
    )


@router.get("/health", response_model=HealthSummary)
async def health_summary() -> HealthSummary:
    """Aggregated health summary of all managed runtime services."""
    statuses = await _runtime_service_statuses()
    total = len(statuses)
    healthy = sum(1 for svc in statuses if svc.health == "healthy")
    unhealthy = sum(1 for svc in statuses if svc.health == "unhealthy")
    running = sum(1 for svc in statuses if svc.state == "running")
    stopped = total - running
    return HealthSummary(total=total, healthy=healthy, unhealthy=unhealthy, running=running, stopped=stopped)
