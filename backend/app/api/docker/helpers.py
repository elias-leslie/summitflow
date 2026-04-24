"""Helper functions for the runtime management API.

Utility functions are defined here. Domain-specific logic is split across:
  - _process_execution.py  — subprocess runners
  - _status_probing.py     — health/status determination
  - _metrics_collection.py — CPU/memory/port telemetry
  - _runtime_control.py    — service lifecycle & mode switching

All symbols are re-exported below for backward compatibility.
"""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from fastapi import Header, HTTPException

# _run_docker is needed by container query functions below.
# This import is NOT circular: _process_execution depends only on constants.
from ._process_execution import _run_docker
from .constants import (
    _DOCKER_GID,  # noqa: F401 — used via helpers.* in _runtime_control
    _DOCKER_SOCKET,  # noqa: F401 — mocked at helpers.* in tests
    _HOST_HOME_PATH,  # noqa: F401 — mocked at helpers.* in tests
    _HOST_REPO_ROOT,  # noqa: F401 — mocked at helpers.* in tests
    _INFRA_SERVICES,
    _INTERNAL_SECRET,
    _REPO_ROOT,  # noqa: F401 — mocked at helpers.* in tests
    _RUNTIME_SERVICE_MAP,
    COMPOSE_PROJECT,
)

# ─── Auth ────────────────────────────────────────────────────────


async def _require_auth(x_internal_secret: str = Header(default="")) -> None:
    """Require internal service secret for mutating runtime endpoints."""
    if not _INTERNAL_SECRET:
        return  # Auth not configured -- allow (dev mode)
    if x_internal_secret != _INTERNAL_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")


def _sanitize_note(note: str) -> str:
    """Whitelist note parameter to safe characters."""
    return re.sub(r"[^a-zA-Z0-9_ -]", "", note)[:100]


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


# ─── Re-exports for backward compatibility ────────────────────────
# All submodule symbols are re-exported so that:
#   - routes.py continues: from .helpers import _service_action, ...
#   - tests continue: mocker.patch("app.api.docker.helpers._run_docker", ...)
#   - __init__.py continues: from .helpers import *

from ._metrics_collection import (  # noqa: E402,F401
    _collect_docker_metrics,
    _listener_pids,
    _ps_metrics,
    _runtime_metrics,
    _signal_port_listeners,
    _systemd_service_metric,
)
from ._process_execution import (  # noqa: E402,F401
    _communicate_with_timeout,
    _run_command,
    _run_journalctl_user,
    _run_systemctl_user,
    _systemctl_user_env,
)
from ._runtime_control import (  # noqa: E402,F401
    _classify_runtime,
    _clear_service_ports,
    _get_runtime_status,
    _helper_image_ref,
    _launch_runtime_switch,
    _persisted_runtime_mode,
    _service_action,
    _st_cli_path,
    _systemd_service_action,
    _write_runtime_mode,
)
from ._status_probing import (  # noqa: E402,F401
    _classify_systemd_state,
    _docker_status,
    _fill_timeout_defaults,
    _parse_docker_health,
    _probe_http,
    _runtime_service_status,
    _runtime_service_statuses,
    _sync_probe_http,
    _systemd_status,
    _systemd_unit_state,
)
