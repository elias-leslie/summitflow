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
import re
import shlex
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

router = APIRouter()

_INTERNAL_SECRET = os.environ.get("INTERNAL_SERVICE_SECRET", "")

def _detect_repo_root(start_path: Path | None = None) -> Path:
    current = (start_path or Path(__file__).resolve()).parent
    for candidate in (current, *current.parents):
        if (candidate / "scripts" / "rebuild.sh").exists():
            return candidate
    return Path(__file__).resolve().parents[3]


_REPO_ROOT = _detect_repo_root()
_HOST_HOME_PATH = Path(os.environ.get("HOST_HOME_PATH", str(Path.home())))
_HOST_REPO_ROOT = Path(os.environ.get("HOST_REPO_ROOT", str(_HOST_HOME_PATH / "summitflow")))
_DEFAULT_STACK_MODE = os.environ.get("SUMMITFLOW_DOCKER_DEFAULT_MODE", "dev")
if _DEFAULT_STACK_MODE not in {"dev", "prod"}:
    _DEFAULT_STACK_MODE = "dev"
_COMPOSE_DIR = Path(os.environ.get("COMPOSE_DIR", str(_REPO_ROOT / "docker" / "compose")))
_COMPOSE_FILE = _COMPOSE_DIR / "docker-compose.yml"
_RUNTIME_MODE_FILE = _COMPOSE_DIR / ".runtime-mode"
_INFRA_SERVICES = {"postgres", "redis", "hatchet", "hatchet-migrate", "hatchet-setup-config"}
_DOCKER_SOCKET = Path("/var/run/docker.sock")


async def _require_auth(x_internal_secret: str = Header(default="")) -> None:
    """Require internal service secret for mutating Docker endpoints."""
    if not _INTERNAL_SECRET:
        return  # Auth not configured — allow (dev mode)
    if x_internal_secret != _INTERNAL_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")


def _sanitize_note(note: str) -> str:
    """Whitelist note parameter to safe characters."""
    return re.sub(r"[^a-zA-Z0-9_ -]", "", note)[:100]

# Compose project name — used to filter containers belonging to our stack
COMPOSE_PROJECT = os.environ.get("COMPOSE_PROJECT_NAME", "summitflow-stack")
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


class DockerRuntimeStatus(BaseModel):
    runtime: Literal["docker", "docker-stopped", "native"]
    current_mode: Literal["dev", "prod"]
    configured_mode: Literal["dev", "prod"]
    default_mode: Literal["dev", "prod"]
    source: Literal["detected", "persisted", "default"]
    is_running: bool


class DockerRuntimeUpdate(BaseModel):
    mode: Literal["dev", "prod"]


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


async def _run_command(*args: str, cwd: Path | None = None) -> tuple[str, str, int]:
    """Run a shell command asynchronously."""
    proc = await asyncio.create_subprocess_exec(
        *args,
        cwd=str(cwd) if cwd else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
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


def _docker_error(detail: str, stderr: str, stdout: str = "") -> HTTPException:
    """Build a concise HTTP error for Docker CLI failures."""
    message = (stderr or stdout or detail).strip()
    return HTTPException(status_code=503, detail=f"{detail}: {message}")


def _service_from_container(container: dict[str, Any]) -> str:
    labels = container.get("Labels", "")
    for label in labels.split(","):
        if label.startswith("com.docker.compose.service="):
            return label.split("=", 1)[1]
    return ""


def _persisted_runtime_mode() -> tuple[Literal["dev", "prod"], Literal["persisted", "default"]]:
    if _RUNTIME_MODE_FILE.exists():
        raw = _RUNTIME_MODE_FILE.read_text().strip()
        if raw in {"dev", "prod"}:
            return raw, "persisted"
    return _DEFAULT_STACK_MODE, "default"


async def _project_containers(*, all_containers: bool = False) -> list[dict[str, Any]]:
    args = ["docker", "ps"]
    if all_containers:
        args.append("--all")
    args.extend(["--format", "json", *_project_filter()])
    stdout, _stderr, rc = await _run_docker(*args)
    if rc != 0 or not stdout.strip():
        return []
    return _parse_json_lines(stdout)


async def _detect_running_mode(containers: list[dict[str, Any]]) -> Literal["dev", "prod"] | None:
    for container in containers:
        service = _service_from_container(container)
        if not service or service in _INFRA_SERVICES:
            continue
        container_id = container.get("ID", "")
        if not container_id:
            continue
        inspect_stdout, _inspect_stderr, rc = await _run_docker(
            "docker",
            "inspect",
            container_id,
            "--format",
            '{{range .Mounts}}{{.Type}} {{.Destination}}{{"\\n"}}{{end}}',
        )
        if rc == 0 and re.search(r"^bind /app/.+", inspect_stdout, flags=re.MULTILINE):
            return "dev"
        return "prod"
    return None


def _rebuild_script_path() -> Path:
    candidates = (
        _HOST_REPO_ROOT / "scripts" / "rebuild.sh",
        _HOST_HOME_PATH / _REPO_ROOT.name / "scripts" / "rebuild.sh",
        _REPO_ROOT / "scripts" / "rebuild.sh",
    )
    for script in candidates:
        if script.exists():
            return script
    return candidates[0]


async def _helper_image_ref() -> str:
    container_ref = os.environ.get("HOSTNAME", "").strip()
    if container_ref:
        stdout, _stderr, rc = await _run_docker(
            "docker",
            "inspect",
            container_ref,
            "--format",
            "{{.Config.Image}}",
        )
        if rc == 0 and stdout.strip():
            return stdout.strip()

    for container in await _project_containers():
        if _service_from_container(container) != "summitflow-api":
            continue
        container_id = container.get("ID", "")
        if not container_id:
            continue
        stdout, _stderr, rc = await _run_docker(
            "docker",
            "inspect",
            container_id,
            "--format",
            "{{.Config.Image}}",
        )
        if rc == 0 and stdout.strip():
            return stdout.strip()

    raise HTTPException(status_code=503, detail="Unable to resolve helper image for Docker mode switch")


async def _launch_runtime_switch(mode: Literal["dev", "prod"], script_path: Path) -> str:
    helper_image = await _helper_image_ref()
    helper_name = f"{COMPOSE_PROJECT}-mode-switch"
    quoted_script = shlex.quote(str(script_path))
    docker_sock_gid = _DOCKER_SOCKET.stat().st_gid if _DOCKER_SOCKET.exists() else None

    await _run_docker("docker", "rm", "-f", helper_name)
    run_args = [
        "docker",
        "run",
        "-d",
        "--name",
        helper_name,
        "--entrypoint",
        "bash",
        "--network",
        "host",
    ]
    if docker_sock_gid is not None:
        run_args.extend(["--group-add", str(docker_sock_gid)])
    run_args.extend(
        [
            "-v",
            "/var/run/docker.sock:/var/run/docker.sock",
            "-v",
            f"{_HOST_HOME_PATH}:{_HOST_HOME_PATH}",
            "-w",
            str(script_path.parent.parent),
            helper_image,
            "-lc",
            f"sleep 2 && exec bash {quoted_script} --{mode} --restart",
        ]
    )
    stdout, stderr, rc = await _run_docker(*run_args)
    if rc != 0 or not stdout.strip():
        raise _docker_error(f"Failed to queue Docker mode switch to {mode}", stderr, stdout)

    return helper_name


async def _get_runtime_status() -> DockerRuntimeStatus:
    configured_mode, source = _persisted_runtime_mode()
    if not _COMPOSE_FILE.exists():
        return DockerRuntimeStatus(
            runtime="native",
            current_mode=configured_mode,
            configured_mode=configured_mode,
            default_mode=_DEFAULT_STACK_MODE,
            source=source,
            is_running=False,
        )

    running_containers = await _project_containers()
    is_running = bool(running_containers)
    detected_mode = await _detect_running_mode(running_containers) if is_running else None
    current_mode = detected_mode or configured_mode
    current_source: Literal["detected", "persisted", "default"]
    if detected_mode:
        current_source = "detected"
    else:
        current_source = source

    return DockerRuntimeStatus(
        runtime="docker" if is_running else "docker-stopped",
        current_mode=current_mode,
        configured_mode=configured_mode,
        default_mode=_DEFAULT_STACK_MODE,
        source=current_source,
        is_running=is_running,
    )


# ─── Endpoints ───────────────────────────────────────────────────


@router.get("/status", response_model=list[ContainerStatus])
async def get_status() -> list[ContainerStatus]:
    """Get all container statuses."""
    stdout, stderr, rc = await _run_docker(
        "docker", "ps", "--all", "--format", "json", *_project_filter()
    )
    if rc != 0:
        raise _docker_error("Docker status unavailable", stderr, stdout)
    if not stdout.strip():
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
        service = _service_from_container(c)

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


@router.get("/runtime", response_model=DockerRuntimeStatus)
async def get_runtime_status() -> DockerRuntimeStatus:
    """Get the current Docker stack mode."""
    return await _get_runtime_status()


@router.post("/runtime", response_model=ActionResult, dependencies=[Depends(_require_auth)])
async def update_runtime_mode(payload: DockerRuntimeUpdate) -> ActionResult:
    """Switch the Docker stack between dev and prod modes."""
    script_path = _rebuild_script_path()
    if not script_path.exists():
        raise HTTPException(status_code=500, detail="rebuild.sh not found")

    runtime = await _get_runtime_status()
    if runtime.current_mode == payload.mode and runtime.is_running:
        return ActionResult(success=True, message=f"Docker stack already running in {payload.mode} mode")

    helper_name = await _launch_runtime_switch(payload.mode, script_path)
    return ActionResult(
        success=True,
        message=f"Queued Docker stack switch to {payload.mode} mode via {helper_name}",
    )


@router.get("/metrics", response_model=list[ContainerMetrics])
async def get_metrics() -> list[ContainerMetrics]:
    """Get CPU/memory per container."""
    # Get container IDs for our project first
    id_stdout, id_stderr, rc = await _run_docker(
        "docker", "ps", "-q", *_project_filter()
    )
    if rc != 0:
        raise _docker_error("Docker metrics unavailable", id_stderr, id_stdout)
    if not id_stdout.strip():
        return []

    container_ids = id_stdout.strip().split()
    stdout, stderr, rc = await _run_docker(
        "docker", "stats", "--no-stream", "--format", "json", *container_ids
    )
    if rc != 0:
        raise _docker_error("Docker metrics unavailable", stderr, stdout)
    if not stdout.strip():
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


@router.post("/restart/{service}", response_model=ActionResult, dependencies=[Depends(_require_auth)])
async def restart_service(service: str) -> ActionResult:
    """Restart a container."""
    container_name = _find_container_name(service)
    _, stderr, rc = await _run_docker("docker", "restart", container_name)
    if rc != 0:
        return ActionResult(success=False, message=stderr.strip())
    return ActionResult(success=True, message=f"Restarted {service}")


@router.post("/stop/{service}", response_model=ActionResult, dependencies=[Depends(_require_auth)])
async def stop_service(service: str) -> ActionResult:
    """Stop a container."""
    container_name = _find_container_name(service)
    _, stderr, rc = await _run_docker("docker", "stop", container_name)
    if rc != 0:
        return ActionResult(success=False, message=stderr.strip())
    return ActionResult(success=True, message=f"Stopped {service}")


@router.post("/start/{service}", response_model=ActionResult, dependencies=[Depends(_require_auth)])
async def start_service(service: str) -> ActionResult:
    """Start a container."""
    container_name = _find_container_name(service)
    _, stderr, rc = await _run_docker("docker", "start", container_name)
    if rc != 0:
        return ActionResult(success=False, message=stderr.strip())
    return ActionResult(success=True, message=f"Started {service}")


@router.post("/backup", response_model=ActionResult, dependencies=[Depends(_require_auth)])
async def create_backup(note: str = "") -> ActionResult:
    """Create an infrastructure backup via the unified backup system.

    Delegates to the backup workflow, creating an infrastructure source if needed.
    Falls back to local pg_dumpall if the workflow system is unavailable.
    """
    note = _sanitize_note(note)

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
    stdout, stderr, rc = await _run_docker(
        "docker", "ps", "--all", "--format", "json", *_project_filter()
    )
    if rc != 0:
        raise _docker_error("Docker health unavailable", stderr, stdout)
    if not stdout.strip():
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
