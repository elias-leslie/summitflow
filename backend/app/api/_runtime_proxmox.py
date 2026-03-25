"""Proxmox VE integration for runtime status dashboard.

Queries the Proxmox API for node and guest (VM/LXC) status,
used by the /api/docker/proxmox endpoint.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import ssl
from typing import Any, Literal, cast
from urllib import error as urllib_error
from urllib import request as urllib_request

from pydantic import BaseModel

from ..utils.env import bool_env as _bool_env
from ..utils.env import float_env as _float_env

_PROXMOX_TIMEOUT_SECONDS = _float_env("SUMMITFLOW_RUNTIME_PROXMOX_TIMEOUT", 5.0)


# ─── Models ──────────────────────────────────────────────────────


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


# ─── Helpers ─────────────────────────────────────────────────────


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


async def get_proxmox_status() -> ProxmoxStatus:
    """Fetch Proxmox cluster status (nodes + guests)."""
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
        guest_type_raw = row.get("type")
        if vmid is None or guest_type_raw not in {"qemu", "lxc"}:
            continue
        guest_type = cast(Literal["qemu", "lxc"], guest_type_raw)
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
