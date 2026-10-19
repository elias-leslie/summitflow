"""Service lifecycle management and the saved runtime mode preference."""

from __future__ import annotations

import asyncio
from typing import Any, Literal, cast

from ...utils import nightshift_stack

# Late-bound access to helpers — ensures mocks at helpers.* take effect at runtime.
from . import helpers as _h
from ._process_execution import _is_system_unit
from .constants import _COMMAND_TIMEOUT_SECONDS, runtime_service_definitions
from .models import ActionResult, RuntimeModeStatus

__all__ = [
    "_classify_runtime",
    "_clear_service_ports",
    "_get_runtime_status",
    "_persisted_runtime_mode",
    "_service_action",
    "_set_service_autostart",
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


async def _get_runtime_status() -> RuntimeModeStatus:
    from .constants import _COMPOSE_FILE, _DEFAULT_STACK_MODE

    default_mode = _normalize_runtime_mode(_DEFAULT_STACK_MODE)
    configured_mode, source = _persisted_runtime_mode()
    statuses = await _h._runtime_service_statuses()
    native_running = any(svc.state == "running" for svc in statuses if svc.manager == "systemd")
    docker_running = any(svc.state == "running" for svc in statuses if svc.manager == "docker")
    return RuntimeModeStatus(
        runtime=_classify_runtime(native_running, docker_running),
        apps_runtime="native" if native_running else "stopped",
        infra_runtime="docker" if docker_running and _COMPOSE_FILE.exists() else "stopped",
        current_mode=configured_mode,
        configured_mode=configured_mode,
        default_mode=default_mode,
        source=source,
        is_running=native_running or docker_running,
    )


def _classify_runtime(
    native_running: bool,
    docker_running: bool,
) -> Literal["docker-stopped", "native", "hybrid"]:
    """Apps are always native; the docker stack only carries infra."""
    if native_running and docker_running:
        return "hybrid"
    if native_running:
        return "native"
    if docker_running:
        return "hybrid"
    return "docker-stopped"


async def _service_action(service: str, action: Literal["start", "stop", "restart"]) -> ActionResult:
    svc = _h._service_definition(service)

    if svc["manager"] == "systemd":
        return await _systemd_service_action(svc, action)

    if not nightshift_stack.stack_installed():
        container_name = _h._find_container_name(svc["container_service"])
        _stdout, stderr, rc = await _h._run_docker("docker", action, container_name)
        if rc != 0:
            return ActionResult(success=False, message=(stderr or f"Failed to {action} {service}").strip())
        return ActionResult(success=True, message=f"{_h._past_tense(action)} {service}")

    # Nightshift has one action per unit, so a container action acts on the whole stack.
    result = await asyncio.to_thread(nightshift_stack.request_stack, action)
    return ActionResult(
        success=result.success, message=f"{result.message} (acts on the whole stack, not only {service})",
        pending=result.pending, approve_url=result.approve_url,
    )


def _systemd_stop_service_defs(svc: dict[str, Any]) -> list[dict[str, Any]]:
    """Return systemd services that must stop to keep an API service down."""
    service = svc["service"]
    project_id = svc.get("project_id")
    if not service.endswith("-api") or not project_id:
        return [svc]

    siblings = [
        candidate
        for candidate in runtime_service_definitions()
        if (
            candidate["manager"] == "systemd"
            and candidate["service"] != service
            and candidate.get("project_id") == project_id
            and not _is_system_unit(candidate.get("unit"))
        )
    ]
    return [*siblings, svc]


def _system_unit_refusal(service: str) -> ActionResult:
    """System-manager units need root; never act on a same-named, disabled user unit."""
    return ActionResult(
        success=False,
        message=(
            f"{service} runs as a system unit; control it with `st service` "
            "(sudo systemctl), not the dashboard"
        ),
    )


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

    if _is_system_unit(svc["unit"]):
        return _system_unit_refusal(service)

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

    if _is_system_unit(unit):
        return _system_unit_refusal(service)

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
