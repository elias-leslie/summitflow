"""Docker management API endpoints.

Provides container status, metrics, logs (SSE), restart/stop/start,
and backup/restore functionality via the Docker CLI.

Note: Inside Docker containers, only the Docker CLI (not compose plugin)
is available. Uses plain `docker` commands with compose project label
filters instead of `docker compose`.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

router = APIRouter()

# Compose project name — used to filter containers belonging to our stack
COMPOSE_PROJECT = os.environ.get("COMPOSE_PROJECT_NAME", "compose")
BACKUP_DIR = Path(os.environ.get("BACKUP_DIR", str(Path.home() / "docker-backups")))


# ─── Models ──────────────────────────────────────────────────────


class ContainerStatus(BaseModel):
    name: str
    service: str
    state: str
    health: str
    status: str
    ports: list[str]


class ContainerMetrics(BaseModel):
    name: str
    cpu_percent: str
    mem_usage: str
    mem_percent: str
    net_io: str
    block_io: str


class HealthSummary(BaseModel):
    total: int
    healthy: int
    unhealthy: int
    running: int
    stopped: int


class ActionResult(BaseModel):
    success: bool
    message: str


# ─── Helpers ─────────────────────────────────────────────────────


async def _run_docker(*args: str, stdin_data: bytes | None = None) -> tuple[str, str, int]:
    """Run a docker command asynchronously."""
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdin=asyncio.subprocess.PIPE if stdin_data else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate(stdin_data)
    return stdout.decode(), stderr.decode(), proc.returncode or 0


def _project_filter() -> list[str]:
    """Return docker filter args for our compose project."""
    return ["--filter", f"label=com.docker.compose.project={COMPOSE_PROJECT}"]


def _find_container_name(service: str) -> str:
    """Build the expected container name for a compose service."""
    return f"{COMPOSE_PROJECT}-{service}-1"


def _parse_json_lines(text: str) -> list[dict[str, Any]]:
    """Parse newline-delimited JSON."""
    results = []
    for line in text.strip().splitlines():
        try:
            results.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return results


# ─── Endpoints ───────────────────────────────────────────────────


@router.get("/status", response_model=list[ContainerStatus])
async def get_status() -> list[ContainerStatus]:
    """Get all container statuses."""
    stdout, _, rc = await _run_docker(
        "docker", "ps", "--all", "--format", "json", *_project_filter()
    )
    if rc != 0 or not stdout.strip():
        return []

    containers = _parse_json_lines(stdout)
    result = []
    for c in containers:
        # docker ps JSON format differs from docker compose ps
        ports_raw = c.get("Ports", "")
        port_strs = []
        if ports_raw:
            for part in ports_raw.split(", "):
                if "->" in part:
                    port_strs.append(part.split("->")[0].split(":")[-1])

        # Extract service name from compose label
        labels = c.get("Labels", "")
        service = ""
        for label in labels.split(","):
            if label.startswith("com.docker.compose.service="):
                service = label.split("=", 1)[1]
                break

        # Map docker ps State to compose-like state
        state = c.get("State", "unknown")
        status_str = c.get("Status", "")

        # Parse health from status string
        health = ""
        if "(healthy)" in status_str:
            health = "healthy"
        elif "(unhealthy)" in status_str:
            health = "unhealthy"
        elif "(health: starting)" in status_str:
            health = "starting"

        result.append(
            ContainerStatus(
                name=c.get("Names", ""),
                service=service,
                state=state,
                health=health,
                status=status_str,
                ports=list(set(port_strs)),
            )
        )
    return result


@router.get("/metrics", response_model=list[ContainerMetrics])
async def get_metrics() -> list[ContainerMetrics]:
    """Get CPU/memory per container."""
    # Get container IDs for our project first
    id_stdout, _, rc = await _run_docker(
        "docker", "ps", "-q", *_project_filter()
    )
    if rc != 0 or not id_stdout.strip():
        return []

    container_ids = id_stdout.strip().split()
    stdout, _, rc = await _run_docker(
        "docker", "stats", "--no-stream", "--format", "json", *container_ids
    )
    if rc != 0 or not stdout.strip():
        return []

    containers = _parse_json_lines(stdout)
    return [
        ContainerMetrics(
            name=c.get("Name", ""),
            cpu_percent=c.get("CPUPerc", "0%"),
            mem_usage=c.get("MemUsage", "0B / 0B"),
            mem_percent=c.get("MemPerc", "0%"),
            net_io=c.get("NetIO", "0B / 0B"),
            block_io=c.get("BlockIO", "0B / 0B"),
        )
        for c in containers
    ]


@router.get("/logs/{service}", response_model=None)
async def get_logs(
    service: str,
    tail: int = Query(default=100, ge=1, le=5000),
    follow: bool = Query(default=False),
) -> StreamingResponse | dict[str, str]:
    """Get container logs. If follow=true, streams via SSE."""
    container_name = _find_container_name(service)

    if follow:

        async def stream_logs():
            proc = await asyncio.create_subprocess_exec(
                "docker", "logs", "-f", "--tail", str(tail), container_name,
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

        return StreamingResponse(
            stream_logs(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    stdout, stderr, rc = await _run_docker(
        "docker", "logs", "--tail", str(tail), container_name
    )
    if rc != 0:
        raise HTTPException(status_code=404, detail=f"Service not found: {service}")
    # docker logs writes to both stdout and stderr
    return {"logs": stdout + stderr}


@router.post("/restart/{service}", response_model=ActionResult)
async def restart_service(service: str) -> ActionResult:
    """Restart a container."""
    container_name = _find_container_name(service)
    _, stderr, rc = await _run_docker("docker", "restart", container_name)
    if rc != 0:
        return ActionResult(success=False, message=stderr.strip())
    return ActionResult(success=True, message=f"Restarted {service}")


@router.post("/stop/{service}", response_model=ActionResult)
async def stop_service(service: str) -> ActionResult:
    """Stop a container."""
    container_name = _find_container_name(service)
    _, stderr, rc = await _run_docker("docker", "stop", container_name)
    if rc != 0:
        return ActionResult(success=False, message=stderr.strip())
    return ActionResult(success=True, message=f"Stopped {service}")


@router.post("/start/{service}", response_model=ActionResult)
async def start_service(service: str) -> ActionResult:
    """Start a container."""
    container_name = _find_container_name(service)
    _, stderr, rc = await _run_docker("docker", "start", container_name)
    if rc != 0:
        return ActionResult(success=False, message=stderr.strip())
    return ActionResult(success=True, message=f"Started {service}")


@router.post("/backup", response_model=ActionResult)
async def create_backup(note: str = "") -> ActionResult:
    """Create an infrastructure backup via the unified backup system.

    Delegates to the backup workflow, creating an infrastructure source if needed.
    Falls back to local pg_dumpall if the workflow system is unavailable.
    """
    try:
        from ..storage import backups as backup_store

        # Ensure infrastructure source exists
        source = backup_store.get_source("infrastructure")
        if not source:
            backup_store.create_source(
                source_id="infrastructure",
                name="Infrastructure",
                path="/",
                source_type="infrastructure",
            )

        # Dispatch via workflow
        from ..workflows.models import BackupInput
        from ..workflows.utility import backup_create_wf

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
    except Exception as e:
        # Fallback to direct pg_dumpall for resilience
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
            success=True, message=f"Backup created: {filename} ({size_mb:.1f} MB) [fallback: {e}]"
        )


@router.get("/health", response_model=HealthSummary)
async def health_summary() -> HealthSummary:
    """Aggregated health summary of all containers."""
    stdout, _, rc = await _run_docker(
        "docker", "ps", "--all", "--format", "json", *_project_filter()
    )
    if rc != 0 or not stdout.strip():
        return HealthSummary(total=0, healthy=0, unhealthy=0, running=0, stopped=0)

    containers = _parse_json_lines(stdout)
    total = len(containers)
    status_strs = [c.get("Status", "") for c in containers]
    healthy = sum(1 for s in status_strs if "(healthy)" in s)
    unhealthy = sum(1 for s in status_strs if "(unhealthy)" in s)
    running = sum(1 for c in containers if c.get("State") == "running")
    stopped = total - running

    return HealthSummary(
        total=total,
        healthy=healthy,
        unhealthy=unhealthy,
        running=running,
        stopped=stopped,
    )
