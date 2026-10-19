"""Route handlers for the runtime management API."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ...config import POSTGRES_PORT
from ...services.runtime_metrics_sampler import clamp_window_minutes
from ...storage import runtime_metrics as runtime_metric_store
from ...utils import nightshift_stack, safe_subprocess
from .._runtime_proxmox import ProxmoxStatus
from .._runtime_proxmox import control_proxmox_guest as _control_proxmox_guest
from .._runtime_proxmox import get_proxmox_status as _get_proxmox_status
from .._runtime_proxmox import set_proxmox_guest_autostart as _set_proxmox_guest_autostart
from ._process_execution import _is_system_unit, _run_command, _run_docker
from .constants import BACKUP_DIR
from .helpers import (
    _find_container_name,
    _get_runtime_status,
    _require_auth,
    _run_journalctl_user,
    _runtime_metrics,
    _runtime_service_statuses,
    _sanitize_note,
    _service_action,
    _service_definition,
    _set_service_autostart,
    _systemctl_user_env,
    _write_runtime_mode,
)
from .models import (
    ActionResult,
    HealthSummary,
    RuntimeMetricSeries,
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


class ProxmoxAutostartUpdate(BaseModel):
    enabled: bool


@router.post(
    "/proxmox/guests/{node}/{guest_type}/{vmid}/autostart",
    dependencies=[Depends(_require_auth)],
)
async def set_proxmox_guest_autostart_endpoint(
    node: str,
    guest_type: Literal["qemu", "lxc"],
    vmid: int,
    payload: ProxmoxAutostartUpdate,
) -> dict[str, Any]:
    """Enable or disable boot auto-start for a Proxmox guest."""
    return await _set_proxmox_guest_autostart(node, guest_type, vmid, payload.enabled)


@router.post(
    "/proxmox/guests/{node}/{guest_type}/{vmid}/{action}",
    dependencies=[Depends(_require_auth)],
)
async def control_proxmox_guest_endpoint(
    node: str,
    guest_type: Literal["qemu", "lxc"],
    vmid: int,
    action: Literal["start", "stop", "shutdown", "reboot"],
) -> dict[str, Any]:
    """Execute power action (start, stop, shutdown, reboot) on a Proxmox guest."""
    return await _control_proxmox_guest(node, guest_type, vmid, action)


@router.post("/runtime", response_model=ActionResult, dependencies=[Depends(_require_auth)])
async def update_runtime_mode(payload: RuntimeModeUpdate) -> ActionResult:
    """Save the preferred Docker parity mode."""
    return _save_mode_preference(await _get_runtime_status(), payload.mode)


def _save_mode_preference(
    runtime: RuntimeModeStatus,
    mode: Literal["dev", "prod"],
) -> ActionResult:
    """Remember the parity preference; live services stay native apps with Docker infra."""
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
    # Read-only: the background sampler owns persistence (runtime_metrics_sampler).
    return await _runtime_metrics()


@router.get("/metrics/history", response_model=list[RuntimeMetricSeries])
async def get_metrics_history(
    service: str | None = Query(default=None),
    manager: str | None = Query(default=None),
    category: str | None = Query(default=None),
    since_minutes: int = Query(default=360, ge=1, le=43200),
    bucket_seconds: int = Query(default=60, ge=15, le=3600),
    limit: int = Query(default=20000, ge=1, le=50000),
) -> list[RuntimeMetricSeries]:
    """Get persisted CPU/memory timelines for runtime services."""
    rows = runtime_metric_store.list_runtime_metric_series(
        service=service,
        manager=manager,
        category=category,
        since_minutes=clamp_window_minutes(since_minutes),
        bucket_seconds=bucket_seconds,
        limit=limit,
    )
    return [RuntimeMetricSeries.model_validate(row) for row in rows]


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
        system_unit = _is_system_unit(svc["unit"])
        proc = safe_subprocess.spawn_pipe(
            [
                "journalctl", *(() if system_unit else ("--user",)), "-u", svc["unit"],
                "-n", str(tail), "-f", "--output=short-iso",
            ],
            env=None if system_unit else _systemctl_user_env(),
            stderr_to_stdout=True,
        )
    else:
        proc = safe_subprocess.spawn_pipe(
            [
                "journalctl", f"CONTAINER_NAME={_find_container_name(svc['container_service'])}",
                "-n", str(tail), "-f", "--output=short-iso",
            ],
            stderr_to_stdout=True,
        )
    try:
        while True:
            line = await proc.readline()
            if not line:
                break
            yield f"data: {line.decode().rstrip()}\n\n"
    finally:
        proc.kill()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except (TimeoutError, ProcessLookupError):
            proc.kill()
        proc.close()


async def _fetch_logs(svc: dict, service: str, tail: int) -> dict[str, str]:
    """Fetch a fixed number of log lines from a service."""
    if svc["manager"] == "systemd":
        journal_args = ("-u", svc["unit"], "-n", str(tail), "--output=short-iso", "--no-pager")
        if _is_system_unit(svc["unit"]):
            stdout, stderr, rc = await _run_command("journalctl", *journal_args)
        else:
            stdout, stderr, rc = await _run_journalctl_user(*journal_args)
        if rc != 0:
            raise HTTPException(status_code=404, detail=f"Service not found: {service}")
        return {"logs": stdout + stderr}

    container = _find_container_name(svc["container_service"])
    if nightshift_stack.stack_installed():
        stdout, stderr, rc = await _run_command(
            "journalctl", f"CONTAINER_NAME={container}", "-n", str(tail), "--output=short-iso", "--no-pager",
        )
    else:
        stdout, stderr, rc = await _run_docker("docker", "logs", "--tail", str(tail), container)
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


@router.post("/enable/{service}", response_model=ActionResult, dependencies=[Depends(_require_auth)])
async def enable_service(service: str) -> ActionResult:
    """Enable boot auto-start for a managed service (does not start it now)."""
    return await _set_service_autostart(service, True)


@router.post("/disable/{service}", response_model=ActionResult, dependencies=[Depends(_require_auth)])
async def disable_service(service: str) -> ActionResult:
    """Disable boot auto-start for a managed service (does not stop it now)."""
    return await _set_service_autostart(service, False)


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
    note_slug = "".join(
        character if character.isalnum() or character in {"-", "_"} else "-"
        for character in note
    ).strip("-")[:80]
    suffix = f"-{note_slug}" if note_slug else ""
    filename = f"docker-pgdump-{timestamp}{suffix}.sql"
    filepath = BACKUP_DIR / filename

    if nightshift_stack.stack_installed():
        stdout, stderr, rc = await _run_command(
            "pg_dumpall", "-h", "localhost", "-p", str(POSTGRES_PORT), "-U", "admin", timeout=None
        )
    else:
        stdout, stderr, rc = await _run_docker(
            "docker", "exec", _find_container_name("postgres"), "pg_dumpall", "-U", "admin"
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
