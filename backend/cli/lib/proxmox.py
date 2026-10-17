"""Small Proxmox API client for `st vm`."""

from __future__ import annotations

import json
import os
import ssl
import subprocess
import sys
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


class ProxmoxTaskError(ProxmoxError):
    """A submitted copy failed or timed out; keep its task identity inspectable."""

    def __init__(self, upid: str) -> None:
        self.upid = upid
        super().__init__(f"Clone task {upid} failed or timed out; inspect the task and destination before retrying")


@dataclass(frozen=True)
class ProxmoxConfig:
    host: str
    token_id: str
    token_secret: str
    node: str
    # PVE cluster CA path (PROXMOX_CA_BUNDLE); TLS is always pinned to it and a missing CA refuses the call
    ca_bundle: str = ""
    # The token may only allocate VMs in this pool (PROXMOX_POOL; empty: no pool, PVE checks /vms/<newid>)
    pool: str = "summitflow"


# PVE pool whose members the token may only start/stop/reset (role SummitFlowPower: VM.PowerMgmt)
POWER_POOL = "summitflow-power"


# Nightshift's world-readable registry finding: which PVE guests are parked or lab assets
NIGHTSHIFT_REGISTRY = Path("/var/lib/nightshift/findings/registry.json")


def reserved_lab_asset(vmid: str, registry: Path | None = None) -> str | None:
    """Nightshift asset id when the VM is a parked or lab-tier guest (its registry check warns when one runs
    undeclared); None for other VMs, templates, or when the registry is unreadable."""
    try:
        findings = json.loads((registry or NIGHTSHIFT_REGISTRY).read_text()).get("findings") or []
        rows = next(f["details"]["assets"] for f in findings if f.get("code") == "assets.registry")
    except (OSError, ValueError, AttributeError, KeyError, TypeError, StopIteration):
        return None
    for row in rows:
        same = isinstance(row, dict) and str(row.get("vmid")) == str(vmid) and row.get("kind") != "template"
        if same and (row.get("presence") == "parked" or row.get("tier") == "lab"):
            return str(row.get("id") or vmid)
    return None


def declare_lab_use(asset: str, hours: float, reason: str) -> None:
    """`nightshift lab-use start` so the board shows who runs the parked machine; fails open with a warning."""
    cmd = ["nightshift", "lab-use", "start", asset, "--hours", f"{hours:g}", "--reason", reason]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=20, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"Warning: could not declare lab use of {asset} with Nightshift ({exc}); starting anyway", file=sys.stderr)
        return
    if result.returncode != 0:
        detail = (result.stdout + result.stderr).strip()[:200] or f"exit {result.returncode}"
        print(f"Warning: Nightshift lab-use declaration for {asset} failed ({detail}); starting anyway", file=sys.stderr)
        return
    print(f"Nightshift: {result.stdout.strip() or f'declared {asset}'}")


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
    # ~/.env.local is the host secret source the backend service already uses;
    # agent shells do not export PROXMOX_* themselves.
    file_values = _read_env_file(Path.home() / ".env.local")
    file_values.update(_read_env_file(get_repo_root() / "docker" / "compose" / ".env"))

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
    ca_bundle = value("PROXMOX_CA_BUNDLE")
    if not ca_bundle or not Path(ca_bundle).is_file():
        raise ProxmoxError(f"PROXMOX_CA_BUNDLE must name the PVE cluster CA file ({ca_bundle or 'unset'}); PVE API calls are refused without it")
    return ProxmoxConfig(
        host=host.rstrip("/"),
        token_id=token_id,
        token_secret=secret,
        node=node,
        ca_bundle=ca_bundle,
        pool=value("PROXMOX_POOL", "summitflow"),
    )


def _tls_context(ca_bundle: str) -> ssl.SSLContext:
    from app.api._runtime_proxmox import ProxmoxTLSConfigError, pinned_ca_context

    try:
        return pinned_ca_context(ca_bundle)
    except ProxmoxTLSConfigError as exc:
        raise ProxmoxError(str(exc)) from exc


class ProxmoxClient:
    def __init__(self, config: ProxmoxConfig | None = None) -> None:
        self.config = config or load_proxmox_config()

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"PVEAPIToken={self.config.token_id}={self.config.token_secret}"}

    def request(self, method: str, path: str, *, data: dict[str, Any] | None = None) -> Any:
        url = f"{self.config.host}/api2/json{path}"
        verify = _tls_context(self.config.ca_bundle)
        try:
            response = httpx.request(
                method,
                url,
                headers=self._headers,
                data=data,
                timeout=30.0,
                verify=verify,
            )
        except httpx.HTTPError as exc:
            raise ProxmoxError(f"Proxmox request failed: {exc}") from exc
        if response.status_code == 403 and "Permission check failed" in response.text:
            raise ProxmoxError(
                f"Proxmox API error 403: {response.text.strip()} (the ST token's VM rights come from PVE pools: "
                f"lifecycle in '{self.config.pool or 'summitflow'}', power only in '{POWER_POOL}'; other VMs are read-only)"
            )
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

    def _kind(self, vmid: str) -> str:
        """'lxc' for a container (e.g. blackbox-vault), else 'qemu': start, stop and status work on both."""
        data = self.request("GET", "/cluster/resources?type=vm")
        rows = data if isinstance(data, list) else []
        row = next((r for r in rows if isinstance(r, dict) and str(r.get("vmid")) == str(vmid)), {})
        return "lxc" if row.get("type") == "lxc" else "qemu"

    def status(self, vmid: str) -> dict[str, Any]:
        data = self.request("GET", f"/nodes/{self.config.node}/{self._kind(vmid)}/{vmid}/status/current")
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

    def clone(self, template: str, newid: str, name: str) -> str:
        """Copy only. Return the submitted task identity; do not imply guest readiness."""
        upid = self.request(
            "POST",
            f"/nodes/{self.config.node}/qemu/{template}/clone",
            data={"newid": newid, "name": name, "full": "1", **({"pool": self.config.pool} if self.config.pool else {})},
        )
        if not isinstance(upid, str) or not upid:
            raise ProxmoxError("Clone submission returned no task identity; inspect destination before retrying")
        try:
            self.wait_task(upid, timeout_seconds=300)
        except ProxmoxError as exc:
            raise ProxmoxTaskError(upid) from exc
        return upid

    def start(self, vmid: str, *, lab_hours: float = 4.0, lab_reason: str = "") -> None:
        # PVE accepts the request before checking state; the task says whether it ran ("already running" fails it).
        self.wait_task(str(self.request("POST", f"/nodes/{self.config.node}/{self._kind(vmid)}/{vmid}/status/start")), timeout_seconds=120)
        # Only a start this call made is declared: a refused start, or a VM someone else already runs, must not get a
        # declaration naming this session (it would hide their undeclared run on the board and replace their claim).
        if asset := reserved_lab_asset(vmid):
            declare_lab_use(asset, lab_hours, lab_reason or f"st vm start {vmid}")

    def stop(self, vmid: str) -> None:
        self.wait_task(str(self.request("POST", f"/nodes/{self.config.node}/{self._kind(vmid)}/{vmid}/status/stop")), timeout_seconds=120)

    def destroy(self, vmid: str) -> None:
        if vmid == "9000" or self.config_get(vmid).get("template"):
            raise ProxmoxError(f"Cannot destroy template VM {vmid}")
        with suppress(ProxmoxError):
            self.request("POST", f"/nodes/{self.config.node}/qemu/{vmid}/status/stop")
        time.sleep(5)
        self.request("DELETE", f"/nodes/{self.config.node}/qemu/{vmid}?purge=1")

    def monitor(self, vmid: str, command: str) -> str:
        """Execute a QEMU monitor command."""
        data = self.request("POST", f"/nodes/{self.config.node}/qemu/{vmid}/monitor", data={"command": command})
        return str(data or "")

    def sendkey(self, vmid: str, keys: str) -> None:
        """Send keystrokes to a VM via QEMU monitor or API."""
        try:
            self.request("POST", f"/nodes/{self.config.node}/qemu/{vmid}/sendkey", data={"key": keys})
        except ProxmoxError:
            # Fallback to monitor command
            self.monitor(vmid, f"sendkey {keys}")

    def agent_exec(self, vmid: str, command: list[str] | str) -> dict[str, Any]:
        """Execute a command inside the guest via QEMU guest agent."""
        cmd_list = [command] if isinstance(command, str) else command
        data = self.request("POST", f"/nodes/{self.config.node}/qemu/{vmid}/agent/exec", data={"command": cmd_list})
        if not isinstance(data, dict):
            raise ProxmoxError(f"Failed to start guest exec on VM {vmid}")
        return data

    def agent_exec_status(self, vmid: str, pid: int) -> dict[str, Any]:
        """Get status and output of a guest agent command execution."""
        data = self.request("GET", f"/nodes/{self.config.node}/qemu/{vmid}/agent/exec-status?pid={pid}")
        if not isinstance(data, dict):
            raise ProxmoxError(f"Failed to get exec status for PID {pid} on VM {vmid}")
        return data

    def config_get(self, vmid: str) -> dict[str, Any]:
        """Get VM hardware configuration."""
        data = self.request("GET", f"/nodes/{self.config.node}/qemu/{vmid}/config")
        if not isinstance(data, dict):
            raise ProxmoxError(f"Failed to get config for VM {vmid}")
        return data

    def config_update(self, vmid: str, data: dict[str, Any]) -> None:
        """Update VM hardware configuration (e.g. CD-ROM attach/eject)."""
        self.request("PUT", f"/nodes/{self.config.node}/qemu/{vmid}/config", data=data)


def snapshot_name_default() -> str:
    return "snap-" + datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
