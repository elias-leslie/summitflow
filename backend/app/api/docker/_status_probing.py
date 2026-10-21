"""Health and status probing for actual Docker containers and systemd units."""

from __future__ import annotations

import asyncio
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request

from ... import runtime_deployment

# Late-bound access to helpers — ensures mocks at helpers.* take effect at runtime.
from . import _process_execution as _pe
from . import helpers as _h
from .constants import _HTTP_PROBE_TIMEOUT_SECONDS, runtime_service_definitions
from .models import RuntimeServiceStatus

__all__ = [
    "_auto_start_from_unit_file_state",
    "_classify_systemd_state",
    "_fill_timeout_defaults",
    "_infra_status",
    "_probe_http",
    "_runtime_service_status",
    "_runtime_service_statuses",
    "_sync_probe_http",
    "_systemd_status",
    "_systemd_unit_state",
]


def _auto_start_from_unit_file_state(unit_file_state: str) -> bool | None:
    """Map systemd UnitFileState to a tri-state auto-start flag.

    enabled/enabled-runtime -> True, disabled -> False. Everything else
    (static, masked, generated, transient, unknown) is not user-togglable -> None.
    """
    if unit_file_state in {"enabled", "enabled-runtime"}:
        return True
    if unit_file_state == "disabled":
        return False
    return None


async def _systemd_unit_state(unit: str) -> dict[str, str]:
    # The host monitor is a system unit; a same-named user unit may exist but is disabled.
    run = _pe._run_systemctl_system if _pe._is_system_unit(unit) else _h._run_systemctl_user
    stdout, stderr, rc = await run(
        "show", unit,
        "-p", "Id", "-p", "LoadState", "-p", "ActiveState",
        "-p", "SubState", "-p", "MainPID", "-p", "ExecMainStatus",
        "-p", "UnitFileState",
    )
    data = _h._parse_systemctl_show(stdout)
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


async def _port_open(port: str) -> bool:
    try:
        _reader, writer = await asyncio.wait_for(
            asyncio.open_connection("127.0.0.1", int(port)), timeout=_HTTP_PROBE_TIMEOUT_SECONDS,
        )
    except (OSError, TimeoutError, ValueError):
        return False
    writer.close()
    return True


async def _infra_status(svc: dict[str, Any]) -> RuntimeServiceStatus:
    """Published ports can be bridges; require the actual local container state."""
    container = _h._find_container_name(svc["container_service"])
    stdout, _stderr, rc = await _h._run_command(
        "sudo", "-n", "docker", "inspect", "--format",
        "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{end}}", container,
    )
    state, _, health = stdout.strip().partition("|")
    known = rc == 0 and state in {"running", "restarting", "created", "exited", "dead", "paused", "removing"}
    running = known and state == "running"
    if running and not health:
        up = await asyncio.gather(*[_port_open(port) for port in svc["ports"]])
        health = "healthy" if up and all(up) else "unhealthy"
    return RuntimeServiceStatus(
        name=container,
        service=svc["service"],
        display_name=svc["display_name"],
        manager="docker",
        category=svc["category"],
        state="unknown" if not known else "running" if running else "starting" if state == "restarting" else "stopped",
        health=health if running else "",
        status=f"Docker {state}" if known else "Docker container state unavailable",
        ports=list(svc["ports"]),
    )


async def _systemd_status(svc: dict[str, Any], unit_state: dict[str, str] | None = None) -> RuntimeServiceStatus:
    """Build status for a systemd-managed service."""
    deployment = runtime_deployment.parse_deployment(svc.get("deployment"))
    if unit_state is None:
        if deployment:
            rows = await _remote_unit_states(deployment, [svc["unit"]])
            unit_state = rows.get(svc["unit"], {})
        else:
            unit_state = await _h._systemd_unit_state(svc["unit"])
    active_state = unit_state.get("ActiveState", "unknown")
    sub_state = unit_state.get("SubState", "unknown")
    load_state = unit_state.get("LoadState", "unknown")
    probe_ok, probe_status = await _h._probe_http(svc.get("probe_url"))

    state, health, status = _classify_systemd_state(
        active_state, sub_state, load_state, probe_ok, probe_status, svc["category"],
    )
    if deployment:
        if load_state == "not-found":
            status = "Unit not installed in guest"
        status = f"{deployment.label}: {unit_state.get('Error') or status}"

    system_unit = not deployment and _pe._is_system_unit(svc["unit"])
    return RuntimeServiceStatus(
        name=svc["unit"],
        service=svc["service"],
        display_name=svc["display_name"],
        manager="systemd",
        category=svc["category"],
        state=state,
        health=health,
        status=f"{status} (system unit)" if system_unit else status,
        ports=list(svc["ports"]),
        auto_start=None if system_unit else _auto_start_from_unit_file_state(unit_state.get("UnitFileState", "")),
        controllable=not system_unit and (not deployment or (load_state == "loaded" and not unit_state.get("Error"))),
        log_streaming=not deployment,
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
    if probe_ok and active_state == "active" and load_state == "loaded":
        return "running", "healthy", f"Serving HTTP {probe_status}"
    if load_state == "not-found":
        return "unknown", "", "Unit not installed locally; remote runtime is not inspected"
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


async def _runtime_service_status(svc: dict[str, Any]) -> RuntimeServiceStatus:
    if svc["manager"] == "docker":
        return await _infra_status(svc)
    return await _systemd_status(svc)


async def _runtime_service_statuses() -> list[RuntimeServiceStatus]:
    definitions = runtime_service_definitions()
    groups: dict[runtime_deployment.ProxmoxDeployment, list[str]] = {}
    for svc in definitions:
        if deployment := runtime_deployment.parse_deployment(svc.get("deployment")):
            groups.setdefault(deployment, []).append(svc["unit"])
    remote = dict(zip(groups, await asyncio.gather(*[
        _remote_unit_states(target, units) for target, units in groups.items()
    ]), strict=True))
    return list(await asyncio.gather(*[
        _systemd_status(svc, remote[target].get(svc["unit"], {}))
        if (target := runtime_deployment.parse_deployment(svc.get("deployment")))
        else _runtime_service_status(svc) for svc in definitions
    ]))


async def _remote_unit_states(target: runtime_deployment.ProxmoxDeployment, units: list[str]) -> dict[str, dict[str, str]]:
    try:
        return await asyncio.to_thread(runtime_deployment.unit_states, target, units)
    except runtime_deployment.DeploymentError as exc:
        return {unit: {"Error": str(exc)} for unit in units}
