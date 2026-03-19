"""Helper functions for the runtime management API."""

from __future__ import annotations

import asyncio
import json
import os
import re
import shlex
from pathlib import Path
from typing import Any, Literal, cast
from urllib import error as urllib_error
from urllib import request as urllib_request

from fastapi import Header, HTTPException

from .constants import (
    _COMMAND_TIMEOUT_SECONDS,
    _DOCKER_SOCKET,
    _HOST_HOME_PATH,
    _HOST_REPO_ROOT,
    _HTTP_PROBE_TIMEOUT_SECONDS,
    _INFRA_SERVICES,
    _INTERNAL_SECRET,
    _REPO_ROOT,
    _RUNTIME_SERVICE_DEFS,
    _RUNTIME_SERVICE_MAP,
    _SYSTEMCTL_TIMEOUT_SECONDS,
    _USER_DBUS_ADDRESS,
    _USER_RUNTIME_DIR,
    COMPOSE_PROJECT,
)
from .models import ActionResult, RuntimeModeStatus, RuntimeServiceMetrics, RuntimeServiceStatus

# ─── Auth ─────────────────────────────────────────────────────────


async def _require_auth(x_internal_secret: str = Header(default="")) -> None:
    """Require internal service secret for mutating runtime endpoints."""
    if not _INTERNAL_SECRET:
        return  # Auth not configured -- allow (dev mode)
    if x_internal_secret != _INTERNAL_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")


def _sanitize_note(note: str) -> str:
    """Whitelist note parameter to safe characters."""
    return re.sub(r"[^a-zA-Z0-9_ -]", "", note)[:100]


# ─── Subprocess runners ──────────────────────────────────────────


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


# ─── Parsing / formatting ────────────────────────────────────────


def _parse_systemctl_show(text: str) -> dict[str, str]:
    data: dict[str, str] = {}
    for line in text.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key] = value
    return data


def _parse_json_lines(text: str) -> list[dict[str, Any]]:
    """Parse newline-delimited JSON."""
    results = []
    for line in text.strip().splitlines():
        try:
            results.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return results


def _format_bytes(num_bytes: float) -> str:
    suffixes = ["B", "KiB", "MiB", "GiB", "TiB"]
    value = float(num_bytes)
    for suffix in suffixes:
        if value < 1024 or suffix == suffixes[-1]:
            return f"{value:.1f}{suffix}" if suffix != "B" else f"{int(value)}B"
        value /= 1024
    return f"{int(num_bytes)}B"


# ─── Docker container helpers ─────────────────────────────────────


def _project_filter() -> list[str]:
    """Return docker filter args for our compose project."""
    return ["--filter", f"label=com.docker.compose.project={COMPOSE_PROJECT}"]


def _find_container_name(service: str) -> str:
    """Build the expected container name for a compose service."""
    return f"{COMPOSE_PROJECT}-{service}-1"


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


def _service_definition(service: str) -> dict[str, Any]:
    svc = _RUNTIME_SERVICE_MAP.get(service)
    if svc is None:
        raise HTTPException(status_code=404, detail=f"Unknown service: {service}")
    return svc


def _past_tense(action: Literal["start", "stop", "restart"]) -> str:
    return {"start": "Started", "stop": "Stopped", "restart": "Restarted"}[action]


# ─── Systemd unit status ─────────────────────────────────────────


async def _systemd_unit_state(unit: str) -> dict[str, str]:
    stdout, stderr, rc = await _run_systemctl_user(
        "show", unit,
        "-p", "Id", "-p", "LoadState", "-p", "ActiveState",
        "-p", "SubState", "-p", "MainPID", "-p", "ExecMainStatus",
    )
    data = _parse_systemctl_show(stdout)
    data.setdefault("Id", unit)

    if rc == 124:
        return _fill_timeout_defaults(data, stderr)

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


def _fill_timeout_defaults(data: dict[str, str], stderr: str) -> dict[str, str]:
    """Fill in defaults for systemctl timeout responses."""
    data.setdefault("LoadState", "unknown")
    data.setdefault("ActiveState", "unknown")
    data.setdefault("SubState", "timed-out")
    data.setdefault("MainPID", "0")
    data.setdefault("ExecMainStatus", "0")
    if stderr:
        data["Error"] = stderr
    return data


# ─── HTTP probing ─────────────────────────────────────────────────


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


# ─── Process / port helpers ───────────────────────────────────────


async def _ps_metrics(pid: int) -> RuntimeServiceMetrics | None:
    stdout, _stderr, rc = await _run_command(
        "ps", "-p", str(pid), "-o", "pid=,%cpu=,%mem=,rss=",
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
    return RuntimeServiceMetrics(
        name=str(pid),
        service="",
        cpu_percent=f"{cpu}%",
        mem_usage=_format_bytes(rss_bytes),
        mem_percent=f"{mem_percent}%",
        net_io="n/a",
        block_io="n/a",
    )


async def _listener_pids(port: str) -> list[int]:
    stdout, _stderr, rc = await _run_command("ss", "-ltnp", f"( sport = :{port} )")
    if rc != 0 or not stdout.strip():
        return []
    return sorted({int(match) for match in re.findall(r"pid=(\d+)", stdout)})


async def _clear_service_ports(svc: dict[str, Any]) -> None:
    for port in svc.get("ports", []):
        await _signal_port_listeners(port, signal=15)
        for _attempt in range(10):
            if not await _listener_pids(port):
                break
            await asyncio.sleep(0.2)
        await _signal_port_listeners(port, signal=9)


async def _signal_port_listeners(port: str, *, signal: int) -> None:
    """Send a signal to all processes listening on the given port."""
    for pid in await _listener_pids(port):
        try:
            os.kill(pid, signal)
        except ProcessLookupError:
            continue


# ─── Container queries ────────────────────────────────────────────


async def _project_containers(*, all_containers: bool = False) -> list[dict[str, Any]]:
    args = ["docker", "ps"]
    if all_containers:
        args.append("--all")
    args.extend(["--format", "json", *_project_filter()])
    stdout, _stderr, rc = await _run_docker(*args)
    if rc != 0 or not stdout.strip():
        return []
    return _parse_json_lines(stdout)


async def _docker_container_map(*, all_containers: bool = True) -> dict[str, dict[str, Any]]:
    containers = await _project_containers(all_containers=all_containers)
    return {
        service: container
        for container in containers
        if (service := _service_from_container(container))
    }


async def _detect_running_mode(containers: list[dict[str, Any]]) -> Literal["dev", "prod"] | None:
    for container in containers:
        service = _service_from_container(container)
        if not service or service in _INFRA_SERVICES:
            continue
        container_id = container.get("ID", "")
        if not container_id:
            continue
        inspect_stdout, _inspect_stderr, rc = await _run_docker(
            "docker", "inspect", container_id,
            "--format", '{{range .Mounts}}{{.Type}} {{.Destination}}{{"\\n"}}{{end}}',
        )
        if rc == 0 and re.search(r"^bind /app/.+", inspect_stdout, flags=re.MULTILINE):
            return "dev"
        return "prod"
    return None


# ─── Runtime mode persistence ─────────────────────────────────────


def _persisted_runtime_mode() -> tuple[Literal["dev", "prod"], Literal["persisted", "default"]]:
    from .constants import _DEFAULT_STACK_MODE, _RUNTIME_MODE_FILE

    if _RUNTIME_MODE_FILE.exists():
        raw = _RUNTIME_MODE_FILE.read_text().strip()
        if raw in {"dev", "prod"}:
            return cast(Literal["dev", "prod"], raw), "persisted"
    return cast(Literal["dev", "prod"], _DEFAULT_STACK_MODE), "default"


def _write_runtime_mode(mode: Literal["dev", "prod"]) -> None:
    from .constants import _RUNTIME_MODE_FILE

    _RUNTIME_MODE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _RUNTIME_MODE_FILE.write_text(f"{mode}\n")


# ─── Service status collection ────────────────────────────────────


async def _docker_status(svc: dict[str, Any], container: dict[str, Any] | None) -> RuntimeServiceStatus:
    """Build status for a Docker-managed service."""
    if container:
        status_str = container.get("Status", "")
        health = _parse_docker_health(status_str)
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


def _parse_docker_health(status_str: str) -> str:
    """Extract health indicator from Docker status string."""
    if "(healthy)" in status_str:
        return "healthy"
    if "(unhealthy)" in status_str:
        return "unhealthy"
    if "(health: starting)" in status_str:
        return "starting"
    return ""


async def _systemd_status(svc: dict[str, Any]) -> RuntimeServiceStatus:
    """Build status for a systemd-managed service."""
    unit_state = await _systemd_unit_state(svc["unit"])
    active_state = unit_state.get("ActiveState", "unknown")
    sub_state = unit_state.get("SubState", "unknown")
    load_state = unit_state.get("LoadState", "unknown")
    probe_ok, probe_status = await _probe_http(svc.get("probe_url"))

    state, health, status = _classify_systemd_state(
        active_state, sub_state, load_state, probe_ok, probe_status, svc["category"],
    )

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


def _classify_systemd_state(
    active_state: str,
    sub_state: str,
    load_state: str,
    probe_ok: bool,
    probe_status: int | None,
    category: str,
) -> tuple[str, str, str]:
    """Return (state, health, status) for a systemd unit."""
    if probe_ok:
        return "running", "healthy", f"Serving HTTP {probe_status}"
    if active_state == "active":
        health = "running" if category == "worker" else ""
        return "running", health, f"systemd {sub_state}"
    if active_state == "activating":
        return "starting", "starting", f"systemd {sub_state}"
    if active_state in {"inactive", "failed", "deactivating"}:
        return "stopped", "", f"systemd {active_state}"
    state = active_state or "unknown"
    status = f"systemd {sub_state}" if sub_state else load_state
    return state, "", status


async def _runtime_service_status(
    svc: dict[str, Any],
    docker_containers: dict[str, dict[str, Any]],
) -> RuntimeServiceStatus:
    if svc["manager"] == "docker":
        container = docker_containers.get(svc["container_service"])
        return await _docker_status(svc, container)
    return await _systemd_status(svc)


async def _runtime_service_statuses() -> list[RuntimeServiceStatus]:
    docker_containers = await _docker_container_map(all_containers=True)
    return list(
        await asyncio.gather(
            *[_runtime_service_status(svc, docker_containers) for svc in _RUNTIME_SERVICE_DEFS]
        )
    )


# ─── Metrics ──────────────────────────────────────────────────────


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


async def _collect_docker_metrics(
    docker_containers: dict[str, dict[str, Any]],
) -> list[RuntimeServiceMetrics]:
    """Collect metrics for all running Docker containers."""
    docker_container_names = {
        container.get("Names", ""): service
        for service, container in docker_containers.items()
    }

    id_stdout, _id_stderr, rc = await _run_docker("docker", "ps", "-q", *_project_filter())
    if rc != 0 or not id_stdout.strip():
        return []

    container_ids = id_stdout.strip().split()
    stdout, _stderr, rc = await _run_docker(
        "docker", "stats", "--no-stream", "--format", "json", *container_ids,
    )
    if rc != 0 or not stdout.strip():
        return []

    return [
        RuntimeServiceMetrics(
            name=c.get("Name", ""),
            service=docker_container_names.get(c.get("Name", ""), c.get("Name", "")),
            cpu_percent=c.get("CPUPerc", "0%"),
            mem_usage=c.get("MemUsage", "0B / 0B"),
            mem_percent=c.get("MemPerc", "0%"),
            net_io=c.get("NetIO", "0B / 0B"),
            block_io=c.get("BlockIO", "0B / 0B"),
        )
        for c in _parse_json_lines(stdout)
    ]


async def _runtime_metrics() -> list[RuntimeServiceMetrics]:
    docker_containers = await _docker_container_map(all_containers=False)
    docker_metrics = await _collect_docker_metrics(docker_containers)

    systemd_metrics = await asyncio.gather(
        *[_systemd_service_metric(svc) for svc in _RUNTIME_SERVICE_DEFS if svc["manager"] == "systemd"]
    )

    return docker_metrics + [m for m in systemd_metrics if m is not None]


# ─── Rebuild / mode switch ────────────────────────────────────────


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
            "docker", "inspect", container_ref, "--format", "{{.Config.Image}}",
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
            "docker", "inspect", container_id, "--format", "{{.Config.Image}}",
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
        "docker", "run", "-d",
        "--name", helper_name,
        "--entrypoint", "bash",
        "--network", "host",
    ]
    if docker_sock_gid is not None:
        run_args.extend(["--group-add", str(docker_sock_gid)])
    run_args.extend([
        "-v", "/var/run/docker.sock:/var/run/docker.sock",
        "-v", f"{_HOST_HOME_PATH}:{_HOST_HOME_PATH}",
        "-w", str(script_path.parent.parent),
        helper_image,
        "-lc", f"sleep 2 && exec bash {quoted_script} --{mode} --restart",
    ])
    stdout, stderr, rc = await _run_docker(*run_args)
    if rc != 0 or not stdout.strip():
        raise _docker_error(f"Failed to queue Docker mode switch to {mode}", stderr, stdout)

    return helper_name


# ─── Runtime status aggregation ───────────────────────────────────


async def _get_runtime_status() -> RuntimeModeStatus:
    from .constants import _COMPOSE_FILE, _DEFAULT_STACK_MODE
    from .models import RuntimeModeStatus

    configured_mode, source = _persisted_runtime_mode()
    statuses = await _runtime_service_statuses()
    native_running = any(svc.state == "running" for svc in statuses if svc.manager == "systemd")
    docker_running = any(svc.state == "running" for svc in statuses if svc.manager == "docker")
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
        c for c in running_containers
        if _service_from_container(c) not in _INFRA_SERVICES
    ]
    docker_app_running = bool(docker_app_containers)
    detected_mode = await _detect_running_mode(running_containers) if docker_app_running else None
    current_mode = detected_mode or configured_mode
    current_source: Literal["detected", "persisted", "default"] = (
        "detected" if detected_mode else source
    )

    runtime = _classify_runtime(native_running, docker_running, docker_app_running)

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


def _classify_runtime(
    native_running: bool,
    docker_running: bool,
    docker_app_running: bool,
) -> Literal["docker", "docker-stopped", "native", "hybrid"]:
    """Determine the overall runtime classification."""
    if native_running and docker_running and not docker_app_running:
        return "hybrid"
    if native_running:
        return "native"
    if docker_app_running:
        return "docker"
    if docker_running:
        return "hybrid"
    return "docker-stopped"


# ─── Service actions ──────────────────────────────────────────────


async def _service_action(service: str, action: Literal["start", "stop", "restart"]) -> ActionResult:
    from .models import ActionResult

    svc = _service_definition(service)

    if svc["manager"] == "systemd":
        return await _systemd_service_action(svc, action)

    container_name = _find_container_name(svc["container_service"])
    _stdout, stderr, rc = await _run_docker("docker", action, container_name)
    if rc != 0:
        return ActionResult(success=False, message=(stderr or f"Failed to {action} {service}").strip())
    return ActionResult(success=True, message=f"{_past_tense(action)} {service}")


async def _systemd_service_action(svc: dict[str, Any], action: Literal["start", "stop", "restart"]) -> ActionResult:
    """Execute a start/stop/restart action on a systemd service."""
    from .models import ActionResult

    service = svc["service"]
    unit = svc["unit"]

    if action == "restart":
        await _run_systemctl_user("stop", unit, timeout=_COMMAND_TIMEOUT_SECONDS)
        await _clear_service_ports(svc)
        _stdout, stderr, rc = await _run_systemctl_user("start", unit, timeout=_COMMAND_TIMEOUT_SECONDS)
    elif action == "stop":
        _stdout, stderr, rc = await _run_systemctl_user("stop", unit, timeout=_COMMAND_TIMEOUT_SECONDS)
        await _clear_service_ports(svc)
    elif action == "start":
        await _clear_service_ports(svc)
        _stdout, stderr, rc = await _run_systemctl_user("start", unit, timeout=_COMMAND_TIMEOUT_SECONDS)
    else:
        _stdout, stderr, rc = await _run_systemctl_user(action, unit, timeout=_COMMAND_TIMEOUT_SECONDS)

    if rc != 0:
        return ActionResult(success=False, message=(stderr or f"Failed to {action} {service}").strip())
    return ActionResult(success=True, message=f"{_past_tense(action)} {service}")
