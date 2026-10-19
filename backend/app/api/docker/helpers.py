"""Helper functions for the runtime management API.

Utility functions are defined here. Domain-specific logic is split across:
  - _process_execution.py  — subprocess runners
  - _status_probing.py     — health/status determination
  - _metrics_collection.py — CPU/memory/port telemetry
  - _runtime_control.py    — service lifecycle & mode preference

All symbols are re-exported below for backward compatibility.
"""

from __future__ import annotations

import hmac
import re
from typing import Any, Literal

from fastapi import Header, HTTPException

from .constants import (
    _INTERNAL_SECRET,
    COMPOSE_PROJECT,
    runtime_service_definitions,
)

# ─── Auth ────────────────────────────────────────────────────────


async def _require_auth(x_internal_secret: str = Header(default="")) -> None:
    """Require internal service secret for mutating runtime endpoints."""
    if not _INTERNAL_SECRET:
        return  # Auth not configured -- allow (dev mode)
    if not hmac.compare_digest(x_internal_secret.encode(), _INTERNAL_SECRET.encode()):
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


def _format_bytes(num_bytes: float) -> str:
    suffixes = ["B", "KiB", "MiB", "GiB", "TiB"]
    value = float(num_bytes)
    for suffix in suffixes:
        if value < 1024 or suffix == suffixes[-1]:
            return f"{value:.1f}{suffix}" if suffix != "B" else f"{int(value)}B"
        value /= 1024
    return f"{int(num_bytes)}B"


# ─── Docker container helpers ─────────────────────────────────────


def _find_container_name(service: str) -> str:
    """Build the expected container name for a compose service."""
    return f"{COMPOSE_PROJECT}-{service}-1"


def _service_definition(service: str) -> dict[str, Any]:
    svc = next((item for item in runtime_service_definitions() if item["service"] == service), None)
    if svc is None:
        raise HTTPException(status_code=404, detail=f"Unknown service: {service}")
    return svc


def _past_tense(action: Literal["start", "stop", "restart"]) -> str:
    return {"start": "Started", "stop": "Stopped", "restart": "Restarted"}[action]


# ─── Re-exports for backward compatibility ────────────────────────
# All submodule symbols are re-exported so that:
#   - routes.py continues: from .helpers import _service_action, ...
#   - tests continue: mocker.patch("app.api.docker.helpers._run_docker", ...)
#   - __init__.py continues: from .helpers import *

from ._metrics_collection import (  # noqa: E402,F401
    _listener_pids,
    _ps_metrics,
    _runtime_metrics,
    _signal_port_listeners,
    _systemd_service_metric,
)
from ._process_execution import (  # noqa: E402,F401
    _communicate_with_timeout,
    _run_command,
    _run_docker,
    _run_journalctl_user,
    _run_systemctl_user,
    _systemctl_user_env,
)
from ._runtime_control import (  # noqa: E402,F401
    _classify_runtime,
    _clear_service_ports,
    _get_runtime_status,
    _persisted_runtime_mode,
    _service_action,
    _set_service_autostart,
    _systemd_service_action,
    _write_runtime_mode,
)
from ._status_probing import (  # noqa: E402,F401
    _auto_start_from_unit_file_state,
    _classify_systemd_state,
    _fill_timeout_defaults,
    _infra_status,
    _probe_http,
    _runtime_service_status,
    _runtime_service_statuses,
    _sync_probe_http,
    _systemd_status,
    _systemd_unit_state,
)
