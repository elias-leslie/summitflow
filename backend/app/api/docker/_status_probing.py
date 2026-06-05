"""Health and status probing for Docker and systemd services."""

from __future__ import annotations

import asyncio
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request

# Late-bound access to helpers — ensures mocks at helpers.* take effect at runtime.
from . import helpers as _h
from .constants import _HTTP_PROBE_TIMEOUT_SECONDS, _RUNTIME_SERVICE_DEFS
from .models import RuntimeServiceStatus

__all__ = [
    "_auto_start_from_unit_file_state",
    "_classify_systemd_state",
    "_docker_status",
    "_fill_timeout_defaults",
    "_parse_docker_health",
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
    stdout, stderr, rc = await _h._run_systemctl_user(
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


def _parse_docker_health(status_str: str) -> str:
    """Extract health indicator from Docker status string."""
    if "(healthy)" in status_str:
        return "healthy"
    if "(unhealthy)" in status_str:
        return "unhealthy"
    if "(health: starting)" in status_str:
        return "starting"
    return ""


async def _docker_status(svc: dict[str, Any], container: dict[str, Any] | None) -> RuntimeServiceStatus:
    """Build status for a Docker-managed service."""
    if container:
        status_str = container.get("Status", "")
        health = _parse_docker_health(status_str)
        state = container.get("State", "unknown")
        return RuntimeServiceStatus(
            name=container.get("Names", _h._find_container_name(svc["container_service"])),
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
        name=_h._find_container_name(svc["container_service"]),
        service=svc["service"],
        display_name=svc["display_name"],
        manager="docker",
        category=svc["category"],
        state="stopped",
        health="",
        status="Docker infra not running",
        ports=list(svc["ports"]),
    )


async def _systemd_status(svc: dict[str, Any]) -> RuntimeServiceStatus:
    """Build status for a systemd-managed service."""
    unit_state = await _h._systemd_unit_state(svc["unit"])
    active_state = unit_state.get("ActiveState", "unknown")
    sub_state = unit_state.get("SubState", "unknown")
    load_state = unit_state.get("LoadState", "unknown")
    probe_ok, probe_status = await _h._probe_http(svc.get("probe_url"))

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
        auto_start=_auto_start_from_unit_file_state(unit_state.get("UnitFileState", "")),
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
    docker_containers = await _h._docker_container_map(all_containers=True)
    return list(
        await asyncio.gather(
            *[_runtime_service_status(svc, docker_containers) for svc in _RUNTIME_SERVICE_DEFS]
        )
    )
