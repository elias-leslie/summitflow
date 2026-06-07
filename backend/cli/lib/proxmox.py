"""Small Proxmox API client for `st vm`."""

from __future__ import annotations

import os
import time
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from app.utils.shared_paths import get_repo_root


class ProxmoxError(RuntimeError):
    """Raised when Proxmox returns an error or required config is missing."""


@dataclass(frozen=True)
class ProxmoxConfig:
    host: str
    token_id: str
    token_secret: str
    node: str


def _read_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not (key.startswith("PROXMOX_") or key.startswith("TEST_VM_")):
            continue
        values[key] = value.strip().strip('"').strip("'")
    return values


def load_proxmox_config() -> ProxmoxConfig:
    env_file = get_repo_root() / "docker" / "compose" / ".env"
    file_values = _read_env_file(env_file)

    def value(name: str, default: str = "") -> str:
        return os.environ.get(name, file_values.get(name, default)).strip()

    host = value("PROXMOX_API_URL")
    token_id = value("PROXMOX_TOKEN_ID")
    secret = value("PROXMOX_TOKEN_SECRET")
    node = value("PROXMOX_NODE")
    missing = [
        name
        for name, configured in (
            ("PROXMOX_API_URL", host),
            ("PROXMOX_TOKEN_ID", token_id),
            ("PROXMOX_TOKEN_SECRET", secret),
            ("PROXMOX_NODE", node),
        )
        if not configured
    ]
    if missing:
        raise ProxmoxError(f"Missing Proxmox configuration: {', '.join(missing)}")
    return ProxmoxConfig(
        host=host.rstrip("/"),
        token_id=token_id,
        token_secret=secret,
        node=node,
    )


class ProxmoxClient:
    def __init__(self, config: ProxmoxConfig | None = None) -> None:
        self.config = config or load_proxmox_config()

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"PVEAPIToken={self.config.token_id}={self.config.token_secret}"}

    def request(self, method: str, path: str, *, data: dict[str, Any] | None = None) -> Any:
        url = f"{self.config.host}/api2/json{path}"
        try:
            response = httpx.request(
                method,
                url,
                headers=self._headers,
                data=data,
                timeout=30.0,
                verify=False,
            )
        except httpx.HTTPError as exc:
            raise ProxmoxError(f"Proxmox request failed: {exc}") from exc
        if response.status_code >= 400:
            raise ProxmoxError(f"Proxmox API error {response.status_code}: {response.text}")
        payload = response.json()
        return payload.get("data")

    def wait_task(self, upid: str, *, timeout_seconds: int = 120) -> None:
        encoded = quote(upid, safe="")
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            status = self.request("GET", f"/nodes/{self.config.node}/tasks/{encoded}/status")
            if isinstance(status, dict) and status.get("status") == "stopped":
                exitstatus = status.get("exitstatus")
                if exitstatus not in (None, "OK"):
                    raise ProxmoxError(f"Proxmox task failed: {exitstatus}")
                return
            time.sleep(2)
        raise ProxmoxError("Timed out waiting for Proxmox task")

    def list_vms(self) -> list[dict[str, Any]]:
        data = self.request("GET", f"/nodes/{self.config.node}/qemu")
        return sorted(data or [], key=lambda item: int(item.get("vmid", 0)))

    def status(self, vmid: str) -> dict[str, Any]:
        data = self.request("GET", f"/nodes/{self.config.node}/qemu/{vmid}/status/current")
        if not isinstance(data, dict):
            raise ProxmoxError(f"Missing status for VM {vmid}")
        return data

    def snapshots(self, vmid: str) -> list[dict[str, Any]]:
        data = self.request("GET", f"/nodes/{self.config.node}/qemu/{vmid}/snapshot")
        snapshots = [item for item in data or [] if item.get("name") != "current"]
        return sorted(snapshots, key=lambda item: str(item.get("name", "")))

    def ip_addresses(self, vmid: str) -> list[str]:
        data = self.request("GET", f"/nodes/{self.config.node}/qemu/{vmid}/agent/network-get-interfaces")
        addresses: list[str] = []
        for iface in (data or {}).get("result", []):
            if iface.get("name") == "lo":
                continue
            for address in iface.get("ip-addresses", []):
                if address.get("ip-address-type") == "ipv4" and address.get("ip-address"):
                    addresses.append(str(address["ip-address"]))
        return addresses

    def snapshot(self, vmid: str, name: str, description: str) -> None:
        upid = self.request(
            "POST",
            f"/nodes/{self.config.node}/qemu/{vmid}/snapshot",
            data={"snapname": name, "description": description},
        )
        self.wait_task(str(upid), timeout_seconds=120)

    def rollback(self, vmid: str, snapshot_name: str) -> None:
        upid = self.request(
            "POST",
            f"/nodes/{self.config.node}/qemu/{vmid}/snapshot/{snapshot_name}/rollback",
        )
        self.wait_task(str(upid), timeout_seconds=120)

    def clone(self, template: str, newid: str, name: str) -> None:
        upid = self.request(
            "POST",
            f"/nodes/{self.config.node}/qemu/{template}/clone",
            data={"newid": newid, "name": name, "full": "1"},
        )
        self.wait_task(str(upid), timeout_seconds=300)

    def start(self, vmid: str) -> None:
        self.request("POST", f"/nodes/{self.config.node}/qemu/{vmid}/status/start")

    def stop(self, vmid: str) -> None:
        self.request("POST", f"/nodes/{self.config.node}/qemu/{vmid}/status/stop")

    def destroy(self, vmid: str) -> None:
        if vmid == "9000":
            raise ProxmoxError("Cannot destroy template VM 9000")
        with suppress(ProxmoxError):
            self.stop(vmid)
        time.sleep(5)
        self.request("DELETE", f"/nodes/{self.config.node}/qemu/{vmid}?purge=1")


def snapshot_name_default() -> str:
    return "snap-" + datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
