"""Service lifecycle management and runtime mode switching."""

from __future__ import annotations

import asyncio
import shlex
from pathlib import Path
from typing import Any, Literal, cast

from fastapi import HTTPException

# Late-bound access to helpers — ensures mocks at helpers.* take effect at runtime.
from . import helpers as _h
from .constants import _COMMAND_TIMEOUT_SECONDS, _INFRA_SERVICES, _RUNTIME_SERVICE_DEFS
from .models import ActionResult, RuntimeModeStatus

__all__ = [
    "_classify_runtime",
    "_clear_service_ports",
    "_get_runtime_status",
    "_helper_image_ref",
    "_launch_runtime_switch",
    "_persisted_runtime_mode",
    "_service_action",
    "_set_service_autostart",
    "_st_cli_path",
    "_systemd_service_action",
    "_write_runtime_mode",
]

RuntimeMode = Literal["dev", "prod"]


def _normalize_runtime_mode(value: str, *, fallback: RuntimeMode = "dev") -> RuntimeMode:
    if value in {"dev", "prod"}:
        return cast(RuntimeMode, value)
    return fallback


async def _clear_service_ports(svc: dict[str, Any]) -> None:
    for port in svc.get("ports", []):
        await _h._signal_port_listeners(port, signal=15)
        for _attempt in range(10):
            if not await _h._listener_pids(port):
                break
            await asyncio.sleep(0.2)
        await _h._signal_port_listeners(port, signal=9)


def _persisted_runtime_mode() -> tuple[RuntimeMode, Literal["persisted", "default"]]:
    from .constants import _DEFAULT_STACK_MODE, _RUNTIME_MODE_FILE

    if _RUNTIME_MODE_FILE.exists():
        raw = _RUNTIME_MODE_FILE.read_text().strip()
        if raw in {"dev", "prod"}:
            return cast(RuntimeMode, raw), "persisted"
    return _normalize_runtime_mode(_DEFAULT_STACK_MODE), "default"


def _write_runtime_mode(mode: RuntimeMode) -> None:
    from .constants import _RUNTIME_MODE_FILE

    _RUNTIME_MODE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _RUNTIME_MODE_FILE.write_text(f"{mode}\n")


def _st_cli_path() -> Path:
    candidates = (
        _h._HOST_REPO_ROOT / "backend" / ".venv" / "bin" / "st",
        _h._HOST_HOME_PATH / "bin" / "st",
        _h._REPO_ROOT / "backend" / ".venv" / "bin" / "st",
    )
    for cli in candidates:
        if cli.exists():
            return cli
    return candidates[0]


async def _helper_image_ref() -> str:
    import os

    container_ref = os.environ.get("HOSTNAME", "").strip()
    if container_ref:
        stdout, _stderr, rc = await _h._run_docker(
            "docker", "inspect", container_ref, "--format", "{{.Config.Image}}",
        )
        if rc == 0 and stdout.strip():
            return stdout.strip()

    for container in await _h._project_containers():
        if _h._service_from_container(container) != "summitflow-api":
            continue
        container_id = container.get("ID", "")
        if not container_id:
            continue
        stdout, _stderr, rc = await _h._run_docker(
            "docker", "inspect", container_id, "--format", "{{.Config.Image}}",
        )
        if rc == 0 and stdout.strip():
            return stdout.strip()

    raise HTTPException(status_code=503, detail="Unable to resolve helper image for Docker mode switch")


async def _launch_runtime_switch(mode: RuntimeMode, st_path: Path) -> str:
    helper_image = await _h._helper_image_ref()
    helper_name = f"{_h.COMPOSE_PROJECT}-mode-switch"
    quoted_st = shlex.quote(str(st_path))
    docker_sock_gid = (
        _h._DOCKER_SOCKET.stat().st_gid if _h._DOCKER_SOCKET.exists()
        else _h._DOCKER_GID
    )

    await _h._run_docker("docker", "rm", "-f", helper_name)
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
        "-v", f"{_h._HOST_HOME_PATH}:{_h._HOST_HOME_PATH}",
        "-w", str(_h._HOST_REPO_ROOT),
        helper_image,
        "-lc", f"sleep 2 && exec {quoted_st} docker up --{mode} --detach",
    ])
    stdout, stderr, rc = await _h._run_docker(*run_args)
    if rc != 0 or not stdout.strip():
        raise _h._docker_error(f"Failed to queue Docker mode switch to {mode}", stderr, stdout)

    return helper_name


async def _get_runtime_status() -> RuntimeModeStatus:
    from .constants import _COMPOSE_FILE, _DEFAULT_STACK_MODE

    default_mode = _normalize_runtime_mode(_DEFAULT_STACK_MODE)
    configured_mode, source = _persisted_runtime_mode()
    statuses = await _h._runtime_service_statuses()
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
            default_mode=default_mode,
            source=source,
            is_running=native_running,
        )

    running_containers = await _h._project_containers()
    docker_app_containers = [
        c for c in running_containers
        if _h._service_from_container(c) not in _INFRA_SERVICES
    ]
    docker_app_running = bool(docker_app_containers)
    detected_mode = await _h._detect_running_mode(running_containers) if docker_app_running else None
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
        default_mode=default_mode,
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


async def _service_action(service: str, action: Literal["start", "stop", "restart"]) -> ActionResult:
    svc = _h._service_definition(service)

    if svc["manager"] == "systemd":
        return await _systemd_service_action(svc, action)

    container_name = _h._find_container_name(svc["container_service"])
    _stdout, stderr, rc = await _h._run_docker("docker", action, container_name)
    if rc != 0:
        return ActionResult(success=False, message=(stderr or f"Failed to {action} {service}").strip())
    return ActionResult(success=True, message=f"{_h._past_tense(action)} {service}")


def _systemd_stop_service_defs(svc: dict[str, Any]) -> list[dict[str, Any]]:
    """Return systemd services that must stop to keep an API service down."""
    service = svc["service"]
    if not service.endswith("-api"):
        return [svc]

    project_prefix = service.removesuffix("-api")
    sibling_prefix = f"{project_prefix}-"
    siblings = [
        candidate
        for candidate in _RUNTIME_SERVICE_DEFS
        if (
            candidate["manager"] == "systemd"
            and candidate["service"] != service
            and candidate["service"].startswith(sibling_prefix)
        )
    ]
    return [*siblings, svc]


async def _set_service_autostart(service: str, enabled: bool) -> ActionResult:
    """Enable or disable boot auto-start for a systemd-managed service.

    Toggles UnitFileState via `systemctl --user enable/disable`. This only
    changes whether the unit starts on boot/login; it does not start or stop
    the running service. Docker infra has no per-unit auto-start toggle.
    """
    svc = _h._service_definition(service)
    if svc["manager"] != "systemd":
        return ActionResult(
            success=False,
            message=f"{service} is Docker infra; auto-start is governed by the compose stack",
        )

    verb = "enable" if enabled else "disable"
    _stdout, stderr, rc = await _h._run_systemctl_user(
        verb, svc["unit"], timeout=_COMMAND_TIMEOUT_SECONDS,
    )
    if rc != 0:
        return ActionResult(
            success=False,
            message=(stderr or f"Failed to {verb} auto-start for {service}").strip(),
        )
    state = "enabled" if enabled else "disabled"
    return ActionResult(success=True, message=f"Auto-start {state} for {service}")


async def _systemd_service_action(svc: dict[str, Any], action: Literal["start", "stop", "restart"]) -> ActionResult:
    """Execute a start/stop/restart action on a systemd service."""
    service = svc["service"]
    unit = svc["unit"]

    if action == "restart":
        await _h._run_systemctl_user("stop", unit, timeout=_COMMAND_TIMEOUT_SECONDS)
        await _h._clear_service_ports(svc)
        _stdout, stderr, rc = await _h._run_systemctl_user("start", unit, timeout=_COMMAND_TIMEOUT_SECONDS)
    elif action == "stop":
        stop_services = _systemd_stop_service_defs(svc)
        _stdout, stderr, rc = await _h._run_systemctl_user(
            "stop",
            *[stop_svc["unit"] for stop_svc in stop_services],
            timeout=_COMMAND_TIMEOUT_SECONDS,
        )
        for stop_svc in stop_services:
            await _h._clear_service_ports(stop_svc)
    elif action == "start":
        await _h._clear_service_ports(svc)
        _stdout, stderr, rc = await _h._run_systemctl_user("start", unit, timeout=_COMMAND_TIMEOUT_SECONDS)
    else:
        _stdout, stderr, rc = await _h._run_systemctl_user(action, unit, timeout=_COMMAND_TIMEOUT_SECONDS)

    if rc != 0:
        return ActionResult(success=False, message=(stderr or f"Failed to {action} {service}").strip())
    return ActionResult(success=True, message=f"{_h._past_tense(action)} {service}")
