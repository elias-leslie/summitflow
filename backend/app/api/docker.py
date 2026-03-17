"""Runtime management API endpoints.

Provides hybrid runtime status, metrics, logs (SSE), restart/stop/start,
Docker parity controls, backup/restore helpers, and Proxmox status for the
SummitFlow ecosystem.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shlex
import ssl
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, cast
from urllib import error as urllib_error
from urllib import request as urllib_request

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

router = APIRouter()

_INTERNAL_SECRET = os.environ.get("INTERNAL_SERVICE_SECRET", "")


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return max(float(raw), 0.1)
    except ValueError:
        return default


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


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
_USER_UID = os.getuid()
_USER_RUNTIME_DIR = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{_USER_UID}"))
_USER_DBUS_ADDRESS = os.environ.get(
    "DBUS_SESSION_BUS_ADDRESS",
    f"unix:path={_USER_RUNTIME_DIR / 'bus'}",
)
_COMMAND_TIMEOUT_SECONDS = _float_env("SUMMITFLOW_RUNTIME_COMMAND_TIMEOUT", 8.0)
_SYSTEMCTL_TIMEOUT_SECONDS = _float_env("SUMMITFLOW_RUNTIME_SYSTEMCTL_TIMEOUT", 0.75)
_HTTP_PROBE_TIMEOUT_SECONDS = _float_env("SUMMITFLOW_RUNTIME_HTTP_PROBE_TIMEOUT", 0.75)
_PROXMOX_TIMEOUT_SECONDS = _float_env("SUMMITFLOW_RUNTIME_PROXMOX_TIMEOUT", 5.0)

_RUNTIME_SERVICE_DEFS: tuple[dict[str, Any], ...] = (
    {
        "service": "summitflow-api",
        "display_name": "summitflow-api",
        "manager": "systemd",
        "category": "app",
        "unit": "summitflow-backend.service",
        "ports": ["8001"],
        "probe_url": "http://localhost:8001/health",
    },
    {
        "service": "summitflow-web",
        "display_name": "summitflow-web",
        "manager": "systemd",
        "category": "app",
        "unit": "summitflow-frontend.service",
        "ports": ["3001"],
        "probe_url": "http://localhost:3001/",
    },
    {
        "service": "summitflow-worker",
        "display_name": "summitflow-worker",
        "manager": "systemd",
        "category": "worker",
        "unit": "summitflow-hatchet-worker.service",
        "ports": [],
    },
    {
        "service": "agent-hub-api",
        "display_name": "agent-hub-api",
        "manager": "systemd",
        "category": "app",
        "unit": "agent-hub-backend.service",
        "ports": ["8003"],
        "probe_url": "http://localhost:8003/health",
    },
    {
        "service": "agent-hub-web",
        "display_name": "agent-hub-web",
        "manager": "systemd",
        "category": "app",
        "unit": "agent-hub-frontend.service",
        "ports": ["3003"],
        "probe_url": "http://localhost:3003/",
    },
    {
        "service": "agent-hub-worker",
        "display_name": "agent-hub-worker",
        "manager": "systemd",
        "category": "worker",
        "unit": "agent-hub-hatchet-worker.service",
        "ports": [],
    },
    {
        "service": "terminal-api",
        "display_name": "terminal-api",
        "manager": "systemd",
        "category": "app",
        "unit": "summitflow-terminal.service",
        "ports": ["8002"],
        "probe_url": "http://localhost:8002/health",
    },
    {
        "service": "terminal-web",
        "display_name": "terminal-web",
        "manager": "systemd",
        "category": "app",
        "unit": "summitflow-terminal-frontend.service",
        "ports": ["3002"],
        "probe_url": "http://localhost:3002/",
    },
    {
        "service": "portfolio-api",
        "display_name": "portfolio-api",
        "manager": "systemd",
        "category": "app",
        "unit": "portfolio-backend.service",
        "ports": ["8000"],
        "probe_url": "http://localhost:8000/health",
    },
    {
        "service": "portfolio-web",
        "display_name": "portfolio-web",
        "manager": "systemd",
        "category": "app",
        "unit": "portfolio-frontend.service",
        "ports": ["3000"],
        "probe_url": "http://localhost:3000/",
    },
    {
        "service": "portfolio-worker",
        "display_name": "portfolio-worker",
        "manager": "systemd",
        "category": "worker",
        "unit": "portfolio-hatchet-worker.service",
        "ports": [],
    },
    {
        "service": "monkey-fight",
        "display_name": "monkey-fight",
        "manager": "systemd",
        "category": "app",
        "unit": "monkey-fight.service",
        "ports": ["4001"],
        "probe_url": "http://localhost:4001/",
    },
    {
        "service": "postgres",
        "display_name": "postgres",
        "manager": "docker",
        "category": "infra",
        "container_service": "postgres",
        "ports": ["5432"],
    },
    {
        "service": "redis",
        "display_name": "redis",
        "manager": "docker",
        "category": "infra",
        "container_service": "redis",
        "ports": ["6379"],
    },
    {
        "service": "hatchet",
        "display_name": "hatchet",
        "manager": "docker",
        "category": "infra",
        "container_service": "hatchet",
        "ports": ["7070", "8888"],
    },
)
_RUNTIME_SERVICE_MAP = {svc["service"]: svc for svc in _RUNTIME_SERVICE_DEFS}


async def _require_auth(x_internal_secret: str = Header(default="")) -> None:
    """Require internal service secret for mutating runtime endpoints."""
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


class RuntimeServiceStatus(BaseModel):
    name: str
    service: str
    display_name: str
    manager: Literal["docker", "systemd"]
    category: Literal["app", "worker", "infra"]
    state: str
    health: str
    status: str
    ports: list[str]


class RuntimeServiceMetrics(BaseModel):
    name: str
    service: str
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


class RuntimeModeStatus(BaseModel):
    runtime: Literal["docker", "docker-stopped", "native", "hybrid"]
    apps_runtime: Literal["docker", "native", "stopped"]
    infra_runtime: Literal["docker", "native", "stopped"]
    current_mode: Literal["dev", "prod"]
    configured_mode: Literal["dev", "prod"]
    default_mode: Literal["dev", "prod"]
    source: Literal["detected", "persisted", "default"]
    is_running: bool


class RuntimeModeUpdate(BaseModel):
    mode: Literal["dev", "prod"]


class ProxmoxNodeStatus(BaseModel):
    node: str
    status: str
    cpu_percent: float | None = None
    memory_used_bytes: int | None = None
    memory_total_bytes: int | None = None
    uptime_seconds: int | None = None


class ProxmoxGuestStatus(BaseModel):
    vmid: int
    name: str
    node: str
    type: Literal["qemu", "lxc"]
    status: str
    cpu_percent: float | None = None
    memory_used_bytes: int | None = None
    memory_total_bytes: int | None = None
    uptime_seconds: int | None = None
    tags: list[str]


class ProxmoxStatus(BaseModel):
    configured: bool
    reachable: bool
    api_url: str | None = None
    error: str | None = None
    nodes: list[ProxmoxNodeStatus]
    guests: list[ProxmoxGuestStatus]


# Backward-compatible aliases while the module and tests still use Docker names.
ContainerStatus = RuntimeServiceStatus
ContainerMetrics = RuntimeServiceMetrics
DockerRuntimeStatus = RuntimeModeStatus
DockerRuntimeUpdate = RuntimeModeUpdate


# ─── Helpers ─────────────────────────────────────────────────────


async def _communicate_with_timeout(
    proc: asyncio.subprocess.Process,
    *,
    stdin_data: bytes | None = None,
    timeout: float | None = None,
) -> tuple[str, str, int]:
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(stdin_data), timeout=timeout)
    except TimeoutError:
        proc.kill()
        try:
            stdout, stderr = await proc.communicate()
        except Exception:
            stdout, stderr = b"", b""
        detail = f"Timed out after {timeout:.2f}s" if timeout is not None else "Timed out"
        return stdout.decode(), detail, 124
    return stdout.decode(), stderr.decode(), proc.returncode or 0


async def _run_docker(
    *args: str,
    stdin_data: bytes | None = None,
    timeout: float | None = None,
) -> tuple[str, str, int]:
    """Run a docker command asynchronously."""
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdin=asyncio.subprocess.PIPE if stdin_data else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    return await _communicate_with_timeout(proc, stdin_data=stdin_data, timeout=timeout)


async def _run_command(
    *args: str,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    timeout: float | None = _COMMAND_TIMEOUT_SECONDS,
) -> tuple[str, str, int]:
    """Run a shell command asynchronously."""
    proc = await asyncio.create_subprocess_exec(
        *args,
        cwd=str(cwd) if cwd else None,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    return await _communicate_with_timeout(proc, timeout=timeout)


def _systemctl_user_env() -> dict[str, str]:
    env = os.environ.copy()
    env["XDG_RUNTIME_DIR"] = str(_USER_RUNTIME_DIR)
    env["DBUS_SESSION_BUS_ADDRESS"] = _USER_DBUS_ADDRESS
    return env


async def _run_systemctl_user(
    *args: str,
    timeout: float = _SYSTEMCTL_TIMEOUT_SECONDS,
) -> tuple[str, str, int]:
    return await _run_command(
        "systemctl",
        "--user",
        *args,
        env=_systemctl_user_env(),
        timeout=timeout,
    )


async def _run_journalctl_user(*args: str) -> tuple[str, str, int]:
    return await _run_command(
        "journalctl",
        "--user",
        *args,
        env=_systemctl_user_env(),
        timeout=_COMMAND_TIMEOUT_SECONDS,
    )


def _parse_systemctl_show(text: str) -> dict[str, str]:
    data: dict[str, str] = {}
    for line in text.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key] = value
    return data


async def _systemd_unit_state(unit: str) -> dict[str, str]:
    stdout, stderr, rc = await _run_systemctl_user(
        "show",
        unit,
        "-p",
        "Id",
        "-p",
        "LoadState",
        "-p",
        "ActiveState",
        "-p",
        "SubState",
        "-p",
        "MainPID",
        "-p",
        "ExecMainStatus",
    )
    data = _parse_systemctl_show(stdout)
    data.setdefault("Id", unit)
    if rc == 124:
        data.setdefault("LoadState", "unknown")
        data.setdefault("ActiveState", "unknown")
        data.setdefault("SubState", "timed-out")
        data.setdefault("MainPID", "0")
        data.setdefault("ExecMainStatus", "0")
        if stderr:
            data["Error"] = stderr
        return data

    if rc != 0 and not data:
        return {
            "Id": unit,
            "LoadState": "unknown",
            "ActiveState": "unknown",
            "SubState": "unavailable",
            "MainPID": "0",
            "ExecMainStatus": "0",
            "Error": stderr.strip() or f"systemctl returned {rc}",
        }

    return data


def _sync_probe_http(url: str, timeout: float) -> tuple[bool, int | None]:
    try:
        with urllib_request.urlopen(url, timeout=timeout) as response:
            return 200 <= response.status < 400, response.status
    except urllib_error.HTTPError as exc:
        return False, exc.code
    except Exception:
        return False, None


async def _probe_http(url: str | None) -> tuple[bool, int | None]:
    if not url:
        return False, None
    return await asyncio.to_thread(_sync_probe_http, url, _HTTP_PROBE_TIMEOUT_SECONDS)


def _format_bytes(num_bytes: float) -> str:
    suffixes = ["B", "KiB", "MiB", "GiB", "TiB"]
    value = float(num_bytes)
    for suffix in suffixes:
        if value < 1024 or suffix == suffixes[-1]:
            return f"{value:.1f}{suffix}" if suffix != "B" else f"{int(value)}B"
        value /= 1024
    return f"{int(num_bytes)}B"


async def _ps_metrics(pid: int) -> ContainerMetrics | None:
    stdout, _stderr, rc = await _run_command(
        "ps",
        "-p",
        str(pid),
        "-o",
        "pid=,%cpu=,%mem=,rss=",
    )
    if rc != 0 or not stdout.strip():
        return None
    parts = stdout.strip().split()
    if len(parts) != 4:
        return None
    _pid, cpu, mem_percent, rss_kib = parts
    try:
        rss_bytes = int(rss_kib) * 1024
    except ValueError:
        rss_bytes = 0
    mem_usage = _format_bytes(rss_bytes)
    return ContainerMetrics(
        name=str(pid),
        service="",
        cpu_percent=f"{cpu}%",
        mem_usage=mem_usage,
        mem_percent=f"{mem_percent}%",
        net_io="n/a",
        block_io="n/a",
    )


async def _listener_pids(port: str) -> list[int]:
    stdout, _stderr, rc = await _run_command("ss", "-ltnp", f"( sport = :{port} )")
    if rc != 0 or not stdout.strip():
        return []

    pids = {
        int(match)
        for match in re.findall(r"pid=(\d+)", stdout)
    }
    return sorted(pids)


async def _clear_service_ports(svc: dict[str, Any]) -> None:
    for port in svc.get("ports", []):
        for pid in await _listener_pids(port):
            try:
                os.kill(pid, 15)
            except ProcessLookupError:
                continue

        for _attempt in range(10):
            if not await _listener_pids(port):
                break
            await asyncio.sleep(0.2)

        for pid in await _listener_pids(port):
            try:
                os.kill(pid, 9)
            except ProcessLookupError:
                continue


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
            return cast(Literal["dev", "prod"], raw), "persisted"
    return cast(Literal["dev", "prod"], _DEFAULT_STACK_MODE), "default"


def _write_runtime_mode(mode: Literal["dev", "prod"]) -> None:
    _RUNTIME_MODE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _RUNTIME_MODE_FILE.write_text(f"{mode}\n")


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


async def _docker_container_map(*, all_containers: bool = True) -> dict[str, dict[str, Any]]:
    containers = await _project_containers(all_containers=all_containers)
    result: dict[str, dict[str, Any]] = {}
    for container in containers:
        service = _service_from_container(container)
        if service:
            result[service] = container
    return result


async def _runtime_service_status(
    svc: dict[str, Any],
    docker_containers: dict[str, dict[str, Any]],
) -> RuntimeServiceStatus:
    if svc["manager"] == "docker":
        container = docker_containers.get(svc["container_service"])
        if container:
            status_str = container.get("Status", "")
            health = ""
            if "(healthy)" in status_str:
                health = "healthy"
            elif "(unhealthy)" in status_str:
                health = "unhealthy"
            elif "(health: starting)" in status_str:
                health = "starting"
            state = container.get("State", "unknown")
            return RuntimeServiceStatus(
                name=container.get("Names", _find_container_name(svc["container_service"])),
                service=svc["service"],
                display_name=svc["display_name"],
                manager="docker",
                category=svc["category"],
                state=state,
                health=health,
                status=status_str or state,
                ports=list(svc["ports"]),
            )

        return RuntimeServiceStatus(
            name=_find_container_name(svc["container_service"]),
            service=svc["service"],
            display_name=svc["display_name"],
            manager="docker",
            category=svc["category"],
            state="stopped",
            health="",
            status="Docker infra not running",
            ports=list(svc["ports"]),
        )

    unit_state = await _systemd_unit_state(svc["unit"])
    active_state = unit_state.get("ActiveState", "unknown")
    sub_state = unit_state.get("SubState", "unknown")
    load_state = unit_state.get("LoadState", "unknown")
    probe_ok, probe_status = await _probe_http(svc.get("probe_url"))

    if probe_ok:
        state = "running"
        health = "healthy"
        status = f"Serving HTTP {probe_status}"
    elif active_state == "active":
        state = "running"
        health = "running" if svc["category"] == "worker" else ""
        status = f"systemd {sub_state}"
    elif active_state == "activating":
        state = "starting"
        health = "starting"
        status = f"systemd {sub_state}"
    elif active_state in {"inactive", "failed", "deactivating"}:
        state = "stopped"
        health = ""
        status = f"systemd {active_state}"
    else:
        state = active_state or "unknown"
        health = ""
        status = f"systemd {sub_state}" if sub_state else load_state

    return RuntimeServiceStatus(
        name=svc["unit"],
        service=svc["service"],
        display_name=svc["display_name"],
        manager="systemd",
        category=svc["category"],
        state=state,
        health=health,
        status=status,
        ports=list(svc["ports"]),
    )


async def _runtime_service_statuses() -> list[RuntimeServiceStatus]:
    docker_containers = await _docker_container_map(all_containers=True)
    return list(
        await asyncio.gather(
            *[_runtime_service_status(svc, docker_containers) for svc in _RUNTIME_SERVICE_DEFS]
        )
    )


async def _systemd_service_metric(svc: dict[str, Any]) -> RuntimeServiceMetrics | None:
    unit_state = await _systemd_unit_state(svc["unit"])
    main_pid_raw = unit_state.get("MainPID", "0")
    try:
        main_pid = int(main_pid_raw)
    except ValueError:
        return None
    if main_pid <= 0:
        return None
    metric = await _ps_metrics(main_pid)
    if metric is None:
        return None
    return RuntimeServiceMetrics(
        name=svc["unit"],
        service=svc["service"],
        cpu_percent=metric.cpu_percent,
        mem_usage=metric.mem_usage,
        mem_percent=metric.mem_percent,
        net_io=metric.net_io,
        block_io=metric.block_io,
    )


async def _runtime_metrics() -> list[RuntimeServiceMetrics]:
    metrics: list[RuntimeServiceMetrics] = []
    docker_containers = await _docker_container_map(all_containers=False)
    docker_container_names = {
        container.get("Names", ""): service
        for service, container in docker_containers.items()
    }

    id_stdout, _id_stderr, rc = await _run_docker("docker", "ps", "-q", *_project_filter())
    if rc == 0 and id_stdout.strip():
        container_ids = id_stdout.strip().split()
        stdout, _stderr, rc = await _run_docker(
            "docker",
            "stats",
            "--no-stream",
            "--format",
            "json",
            *container_ids,
        )
        if rc == 0 and stdout.strip():
            for c in _parse_json_lines(stdout):
                name = c.get("Name", "")
                service = docker_container_names.get(name, name)
                metrics.append(
                    RuntimeServiceMetrics(
                        name=name,
                        service=service,
                        cpu_percent=c.get("CPUPerc", "0%"),
                        mem_usage=c.get("MemUsage", "0B / 0B"),
                        mem_percent=c.get("MemPerc", "0%"),
                        net_io=c.get("NetIO", "0B / 0B"),
                        block_io=c.get("BlockIO", "0B / 0B"),
                    )
                )

    systemd_metrics = await asyncio.gather(
        *[_systemd_service_metric(svc) for svc in _RUNTIME_SERVICE_DEFS if svc["manager"] == "systemd"]
    )
    metrics.extend(metric for metric in systemd_metrics if metric is not None)

    return metrics


def _proxmox_config() -> dict[str, Any]:
    return {
        "api_url": os.environ.get("PROXMOX_API_URL", "").strip().rstrip("/"),
        "token_id": os.environ.get("PROXMOX_TOKEN_ID", "").strip(),
        "token_secret": os.environ.get("PROXMOX_TOKEN_SECRET", "").strip(),
        "verify_ssl": _bool_env("PROXMOX_VERIFY_SSL", default=False),
    }


def _split_proxmox_tags(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [tag for tag in re.split(r"[;,]", raw) if tag]


def _cpu_percent(value: Any) -> float | None:
    try:
        return round(float(value) * 100, 1)
    except (TypeError, ValueError):
        return None


def _int_value(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _sync_proxmox_get_json(
    api_url: str,
    token_id: str,
    token_secret: str,
    path: str,
    *,
    verify_ssl: bool,
) -> Any:
    request = urllib_request.Request(
        f"{api_url}/api2/json{path}",
        headers={"Authorization": f"PVEAPIToken={token_id}={token_secret}"},
    )
    context = None if verify_ssl else ssl._create_unverified_context()
    with urllib_request.urlopen(
        request,
        timeout=_PROXMOX_TIMEOUT_SECONDS,
        context=context,
    ) as response:
        payload = json.load(response)
    return payload.get("data")


def _proxmox_error_message(exc: Exception) -> str:
    if isinstance(exc, urllib_error.HTTPError):
        return f"{exc.code} {exc.reason}"
    if isinstance(exc, urllib_error.URLError):
        return str(exc.reason)
    return str(exc)


async def _get_proxmox_status() -> ProxmoxStatus:
    config = _proxmox_config()
    api_url = config["api_url"]
    token_id = config["token_id"]
    token_secret = config["token_secret"]
    verify_ssl = config["verify_ssl"]
    configured = bool(api_url and token_id and token_secret)

    if not configured:
        return ProxmoxStatus(
            configured=False,
            reachable=False,
            api_url=api_url or None,
            error="Set PROXMOX_API_URL, PROXMOX_TOKEN_ID, and PROXMOX_TOKEN_SECRET to enable Proxmox status.",
            nodes=[],
            guests=[],
        )

    try:
        node_rows, guest_rows = await asyncio.gather(
            asyncio.to_thread(
                _sync_proxmox_get_json,
                api_url,
                token_id,
                token_secret,
                "/cluster/resources?type=node",
                verify_ssl=verify_ssl,
            ),
            asyncio.to_thread(
                _sync_proxmox_get_json,
                api_url,
                token_id,
                token_secret,
                "/cluster/resources?type=vm",
                verify_ssl=verify_ssl,
            ),
        )
    except Exception as exc:
        return ProxmoxStatus(
            configured=True,
            reachable=False,
            api_url=api_url,
            error=_proxmox_error_message(exc),
            nodes=[],
            guests=[],
        )

    nodes = [
        ProxmoxNodeStatus(
            node=str(row.get("node") or row.get("id") or "unknown"),
            status=str(row.get("status") or "unknown"),
            cpu_percent=_cpu_percent(row.get("cpu")),
            memory_used_bytes=_int_value(row.get("mem")),
            memory_total_bytes=_int_value(row.get("maxmem")),
            uptime_seconds=_int_value(row.get("uptime")),
        )
        for row in (node_rows or [])
        if isinstance(row, dict)
    ]

    guests: list[ProxmoxGuestStatus] = []
    for row in guest_rows or []:
        if not isinstance(row, dict):
            continue
        vmid = _int_value(row.get("vmid"))
        guest_type = str(row.get("type") or "")
        if vmid is None or guest_type not in {"qemu", "lxc"}:
            continue
        guests.append(
            ProxmoxGuestStatus(
                vmid=vmid,
                name=str(row.get("name") or f"{guest_type}-{vmid}"),
                node=str(row.get("node") or "unknown"),
                type=guest_type,
                status=str(row.get("status") or "unknown"),
                cpu_percent=_cpu_percent(row.get("cpu")),
                memory_used_bytes=_int_value(row.get("mem")),
                memory_total_bytes=_int_value(row.get("maxmem")),
                uptime_seconds=_int_value(row.get("uptime")),
                tags=_split_proxmox_tags(row.get("tags")),
            )
        )

    nodes.sort(key=lambda node: node.node)
    guests.sort(key=lambda guest: (guest.node, guest.vmid))

    return ProxmoxStatus(
        configured=True,
        reachable=True,
        api_url=api_url,
        nodes=nodes,
        guests=guests,
    )


def _service_definition(service: str) -> dict[str, Any]:
    svc = _RUNTIME_SERVICE_MAP.get(service)
    if svc is None:
        raise HTTPException(status_code=404, detail=f"Unknown service: {service}")
    return svc


def _past_tense(action: Literal["start", "stop", "restart"]) -> str:
    return {
        "start": "Started",
        "stop": "Stopped",
        "restart": "Restarted",
    }[action]


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


async def _get_runtime_status() -> RuntimeModeStatus:
    configured_mode, source = _persisted_runtime_mode()
    statuses = await _runtime_service_statuses()
    native_statuses = [svc for svc in statuses if svc.manager == "systemd"]
    docker_statuses = [svc for svc in statuses if svc.manager == "docker"]
    native_running = any(svc.state == "running" for svc in native_statuses)
    docker_running = any(svc.state == "running" for svc in docker_statuses)
    apps_runtime: Literal["docker", "native", "stopped"] = "native" if native_running else "stopped"
    infra_runtime: Literal["docker", "native", "stopped"] = "docker" if docker_running else "stopped"

    if not _COMPOSE_FILE.exists():
        return RuntimeModeStatus(
            runtime="native",
            apps_runtime=apps_runtime,
            infra_runtime="stopped",
            current_mode=configured_mode,
            configured_mode=configured_mode,
            default_mode=_DEFAULT_STACK_MODE,
            source=source,
            is_running=native_running,
        )

    running_containers = await _project_containers()
    docker_app_containers = [
        container
        for container in running_containers
        if _service_from_container(container) not in _INFRA_SERVICES
    ]
    docker_app_running = bool(docker_app_containers)
    detected_mode = await _detect_running_mode(running_containers) if docker_app_running else None
    current_mode = detected_mode or configured_mode
    current_source: Literal["detected", "persisted", "default"] = (
        "detected" if detected_mode else source
    )

    if native_running and docker_running and not docker_app_running:
        runtime: Literal["docker", "docker-stopped", "native", "hybrid"] = "hybrid"
    elif native_running:
        runtime = "native"
    elif docker_app_running:
        runtime = "docker"
    elif docker_running:
        runtime = "hybrid"
    else:
        runtime = "docker-stopped"

    return RuntimeModeStatus(
        runtime=runtime,
        apps_runtime=apps_runtime if runtime != "docker" else "docker",
        infra_runtime=infra_runtime,
        current_mode=current_mode,
        configured_mode=configured_mode,
        default_mode=_DEFAULT_STACK_MODE,
        source=current_source,
        is_running=native_running or docker_running or docker_app_running,
    )


async def _service_action(service: str, action: Literal["start", "stop", "restart"]) -> ActionResult:
    svc = _service_definition(service)
    if svc["manager"] == "systemd":
        if action == "restart":
            await _run_systemctl_user("stop", svc["unit"], timeout=_COMMAND_TIMEOUT_SECONDS)
            await _clear_service_ports(svc)
            _stdout, stderr, rc = await _run_systemctl_user(
                "start",
                svc["unit"],
                timeout=_COMMAND_TIMEOUT_SECONDS,
            )
        elif action == "stop":
            _stdout, stderr, rc = await _run_systemctl_user(
                "stop",
                svc["unit"],
                timeout=_COMMAND_TIMEOUT_SECONDS,
            )
            await _clear_service_ports(svc)
        elif action == "start":
            await _clear_service_ports(svc)
            _stdout, stderr, rc = await _run_systemctl_user(
                "start",
                svc["unit"],
                timeout=_COMMAND_TIMEOUT_SECONDS,
            )
        else:
            _stdout, stderr, rc = await _run_systemctl_user(
                action,
                svc["unit"],
                timeout=_COMMAND_TIMEOUT_SECONDS,
            )
        if rc != 0:
            return ActionResult(success=False, message=(stderr or f"Failed to {action} {service}").strip())
        return ActionResult(success=True, message=f"{_past_tense(action)} {service}")

    container_name = _find_container_name(svc["container_service"])
    _stdout, stderr, rc = await _run_docker("docker", action, container_name)
    if rc != 0:
        return ActionResult(success=False, message=(stderr or f"Failed to {action} {service}").strip())
    return ActionResult(success=True, message=f"{_past_tense(action)} {service}")


# ─── Endpoints ───────────────────────────────────────────────────


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
        if runtime.configured_mode == payload.mode:
            return ActionResult(
                success=True,
                message=(
                    f"Docker parity preference already set to {payload.mode}. "
                    "Live services remain native apps with Docker infra."
                ),
            )

        _write_runtime_mode(payload.mode)
        return ActionResult(
            success=True,
            message=(
                f"Saved Docker parity preference: {payload.mode}. "
                "Live services remain native apps with Docker infra."
            ),
        )

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


@router.get("/metrics", response_model=list[RuntimeServiceMetrics])
async def get_metrics() -> list[RuntimeServiceMetrics]:
    """Get CPU/memory metrics for managed runtime services."""
    return await _runtime_metrics()


@router.get("/logs/{service}", response_model=None)
async def get_logs(
    service: str,
    tail: int = Query(default=100, ge=1, le=5000),
    follow: bool = Query(default=False),
) -> StreamingResponse | dict[str, str]:
    """Get service logs. If follow=true, streams via SSE."""
    svc = _service_definition(service)

    if follow:

        async def stream_logs():
            if svc["manager"] == "systemd":
                proc = await asyncio.create_subprocess_exec(
                    "journalctl",
                    "--user",
                    "-u",
                    svc["unit"],
                    "-n",
                    str(tail),
                    "-f",
                    "--output=short-iso",
                    env=_systemctl_user_env(),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                )
            else:
                proc = await asyncio.create_subprocess_exec(
                    "docker",
                    "logs",
                    "-f",
                    "--tail",
                    str(tail),
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

        return StreamingResponse(
            stream_logs(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    if svc["manager"] == "systemd":
        stdout, stderr, rc = await _run_journalctl_user(
            "-u",
            svc["unit"],
            "-n",
            str(tail),
            "--output=short-iso",
            "--no-pager",
        )
        if rc != 0:
            raise HTTPException(status_code=404, detail=f"Service not found: {service}")
        return {"logs": stdout + stderr}

    stdout, stderr, rc = await _run_docker(
        "docker",
        "logs",
        "--tail",
        str(tail),
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
    """Aggregated health summary of all managed runtime services."""
    statuses = await _runtime_service_statuses()
    total = len(statuses)
    healthy = sum(1 for svc in statuses if svc.health == "healthy")
    unhealthy = sum(1 for svc in statuses if svc.health == "unhealthy")
    running = sum(1 for svc in statuses if svc.state == "running")
    stopped = total - running
    return HealthSummary(total=total, healthy=healthy, unhealthy=unhealthy, running=running, stopped=stopped)
