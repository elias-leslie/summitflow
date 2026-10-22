"""Small Proxmox API client for `st vm`."""

from __future__ import annotations

import json
import os
import re
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

from app.utils.shared_paths import get_compose_env_file


class ProxmoxError(RuntimeError):
    """Raised when Proxmox returns an error or required config is missing."""


class ProxmoxTokenMissing(ProxmoxError):
    """No Proxmox API token is configured here (an agent shell); `st vm` then goes through the backend route."""


class ProxmoxTaskError(ProxmoxError):
    """A submitted copy failed or timed out; keep its task identity inspectable."""

    def __init__(self, upid: str) -> None:
        self.upid = upid
        super().__init__(f"Clone task {upid} failed or timed out; inspect the task and destination before retrying")


# Expected external failures at HTTP/JSON and task-polling boundaries. Programming errors must surface.
LAB_TRANSPORT_ERRORS = (httpx.HTTPError, httpx.InvalidURL, OSError, json.JSONDecodeError, UnicodeError)
_LAB_SCOPE = object()


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


# PVE pool of production guests the token may start/stop/reboot, resize, and configure startup options
# (role SummitFlowOps: VM.PowerMgmt, VM.Config.CPU, VM.Config.Memory, VM.Config.Options);
# never destroy, snapshot, roll back, or change disks/network
OPS_POOL = "summitflow-ops"
# PVE pool whose members the token may only start/stop/reset (role SummitFlowPower: VM.PowerMgmt)
POWER_POOL = "summitflow-power"

LAB_OBSERVE_MAX_VMS = 32
LAB_TASK_LIMIT = 1000


def validate_lab_vmids(vmids: object) -> None:
    """Canonical PVE IDs only; bound the work before any client or API access."""
    if not isinstance(vmids, list) or not 1 <= len(vmids) <= LAB_OBSERVE_MAX_VMS:
        raise ProxmoxError(f"Pass 1 to {LAB_OBSERVE_MAX_VMS} explicit VM IDs")
    if any(not isinstance(vmid, str) or not re.fullmatch(r"[1-9][0-9]{2,8}", vmid) for vmid in vmids):
        raise ProxmoxError("VM IDs must be canonical decimal strings from 100 to 999999999")
    if len(set(vmids)) != len(vmids):
        raise ProxmoxError("VM IDs must be unique")


def validate_lab_observe(vmids: object, storage: object) -> None:
    validate_lab_vmids(vmids)
    if not isinstance(storage, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,62}[A-Za-z0-9]", storage):
        raise ProxmoxError("Storage must be a configured PVE storage ID of 2 to 64 characters")


def validate_lab_reset(vmid: object, name: object, snapshot: object) -> None:
    validate_lab_vmids([vmid])
    if not isinstance(name, str) or len(name) > 253 or not all(
        re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label) for label in name.split(".")
    ):
        raise ProxmoxError("Name must be an exact PVE guest hostname")
    if not isinstance(snapshot, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{1,39}", snapshot) or snapshot == "current":
        raise ProxmoxError("Snapshot must be an exact PVE snapshot name (2 to 40 characters), excluding current")


def validate_lab_observation(result: Any, vmids: list[str], storage: str) -> None:
    """Refuse incomplete remote evidence and unexpected fields rather than printing a partial success."""
    row_keys = {"vmid", "name", "status", "uptime", "lock", "snapshots", "latest_tasks"}
    if not isinstance(result, dict) or set(result) != {"vms", "storage"} or not isinstance(result["vms"], list):
        raise ProxmoxError("Proxmox observe returned no complete result")
    rows, capacity = result["vms"], result["storage"]
    if len(rows) != len(vmids) or any(
        not isinstance(row, dict) or set(row) != row_keys or type(row["vmid"]) is not int or str(row["vmid"]) != vmid
        or not isinstance(row["name"], str) or not row["name"] or row["status"] not in ("running", "stopped")
        or type(row["uptime"]) is not int or row["uptime"] < 0 or (row["lock"] is not None and not isinstance(row["lock"], str))
        or not isinstance(row["snapshots"], list) or any(not isinstance(name, str) or not name for name in row["snapshots"])
        or not isinstance(row["latest_tasks"], dict) or set(row["latest_tasks"]) != {"qmstart", "qmrollback"}
        or any(value is not None and (type(value) is not int or value <= 0) for value in row["latest_tasks"].values())
        for row, vmid in zip(rows, vmids, strict=True)
    ) or (
        not isinstance(capacity, dict) or set(capacity) != {"name", "total", "used", "available"} or capacity["name"] != storage
        or any(type(capacity[key]) is not int or capacity[key] < 0 for key in ("total", "used", "available"))
        or capacity["total"] <= 0 or capacity["used"] > capacity["total"] or capacity["available"] > capacity["total"]
    ):
        raise ProxmoxError("Proxmox observe returned no complete result")


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


def declare_if_lab(vmid: str, hours: float, reason: str) -> None:
    """Only a start this call made is declared: a refused start, or a VM someone else already runs, must not get a
    declaration naming this session (it would hide their undeclared run on the board and replace their claim)."""
    if asset := reserved_lab_asset(vmid):
        declare_lab_use(asset, hours, reason or f"st vm start {vmid}")


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


ADMIN_TOKEN_ENV = "PROXMOX_ADMIN_TOKEN"


def parse_admin_token(value: str) -> tuple[str, str]:
    """PVE's own token form `user@realm!name=secret` -> (token id, secret); never echoes the value."""
    token_id, sep, secret = value.partition("=")
    if "!" not in token_id or not sep or not secret or token_id.startswith("!") or token_id.endswith("!"):
        raise ProxmoxError(f"{ADMIN_TOKEN_ENV} is malformed; expected user@realm!tokenname=secret")
    return token_id, secret


def load_proxmox_config(*, allow_admin_token: bool = True) -> ProxmoxConfig:
    # ~/.env.local is the host secret source the backend service already uses;
    # agent shells do not export PROXMOX_* themselves.
    file_values = _read_env_file(Path.home() / ".env.local")
    file_values.update(_read_env_file(get_compose_env_file()))

    def value(name: str, default: str = "") -> str:
        return os.environ.get(name, file_values.get(name, default)).strip()

    host = value("PROXMOX_API_URL")
    token_id = value("PROXMOX_TOKEN_ID")
    secret = value("PROXMOX_TOKEN_SECRET")
    if allow_admin_token and (admin_token := os.environ.get(ADMIN_TOKEN_ENV, "").strip()):  # legacy elevation; env only
        token_id, secret = parse_admin_token(admin_token)
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
        if {"PROXMOX_API_URL", "PROXMOX_TOKEN_ID", "PROXMOX_TOKEN_SECRET"} & set(missing):
            raise ProxmoxTokenMissing(f"Missing Proxmox configuration: {', '.join(missing)}")
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
        self.__lab_scope: object | None = None
        self.config = config or load_proxmox_config()

    @property
    def _lab_scoped(self) -> bool:
        return self.__lab_scope is _LAB_SCOPE

    @classmethod
    def for_lab(cls) -> ProxmoxClient:
        """Use only the configured automation token, regardless of owner elevation in this process."""
        try:
            config = load_proxmox_config(allow_admin_token=False)
        except ProxmoxTokenMissing:
            raise  # tokenless shells use the unelevated backend route
        except (ProxmoxError, OSError, UnicodeError, json.JSONDecodeError):
            raise ProxmoxError("Proxmox client unavailable; check configured API access") from None
        client = cls(config)
        client.__lab_scope = _LAB_SCOPE
        return client

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
                f"full lifecycle in '{self.config.pool or 'summitflow'}', power + cores/memory in '{OPS_POOL}', "
                f"power only in '{POWER_POOL}'; everything else is read-only; production destroy/rollback/disk changes: "
                f"st elevate request proxmox-admin --reason '...' --wait, then st elevate run proxmox-admin -- st vm ...)"
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
        """Every guest, VMs and containers alike, so an ID in use by either shows up."""
        data = self.request("GET", "/cluster/resources?type=vm")
        rows = [r for r in data or [] if isinstance(r, dict) and r.get("node", self.config.node) == self.config.node]
        return sorted(rows, key=lambda item: int(item.get("vmid", 0)))

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

    def _lab_request(self, method: str, path: str, component: str, *, data: dict[str, Any] | None = None) -> Any:
        # These machine-readable operations never include transport/config values or raw API bodies in errors.
        try:
            return self.request(method, path, data=data)
        except (ProxmoxError, *LAB_TRANSPORT_ERRORS):
            raise ProxmoxError(f"Proxmox {component} unavailable; no complete result") from None

    def _require_lab_assets(self, vmids: list[str]) -> None:
        if not self._lab_scoped:
            raise ProxmoxError("Lab operations require an unelevated ProxmoxClient.for_lab()")
        if any(reserved_lab_asset(vmid) is None for vmid in vmids):
            raise ProxmoxError("Every VM must be a registered Nightshift lab or parked asset")

    def _lab_state(self, vmid: str) -> tuple[dict[str, Any], dict[str, Any]]:
        base = f"/nodes/{self.config.node}/qemu/{vmid}"
        status = self._lab_request("GET", f"{base}/status/current", f"VM {vmid} status")
        config = self._lab_request("GET", f"{base}/config", f"VM {vmid} config")
        if (
            not isinstance(status, dict) or not isinstance(config, dict)
            or str(status.get("vmid")) != vmid or status.get("status") not in ("running", "stopped")
            or not isinstance(status.get("name"), str) or not status["name"] or config.get("name") != status["name"]
            or type(status.get("uptime")) is not int or status["uptime"] < 0
            or ("lock" in config and (not isinstance(config["lock"], str) or not config["lock"]))
        ):
            raise ProxmoxError(f"Incomplete or inconsistent state for VM {vmid}")
        return status, config

    def _lab_snapshots(self, vmid: str) -> dict[str, dict[str, Any]]:
        rows = self._lab_request("GET", f"/nodes/{self.config.node}/qemu/{vmid}/snapshot", f"VM {vmid} snapshots")
        if not isinstance(rows, list) or any(
            not isinstance(row, dict) or not isinstance(row.get("name"), str)
            or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{1,39}", row["name"])
            or row.get("snapstate") for row in rows
        ):
            raise ProxmoxError(f"Incomplete snapshots for VM {vmid}")
        snapshots = {row["name"]: row for row in rows}
        if "current" not in snapshots or len(snapshots) != len(rows):
            raise ProxmoxError(f"Incomplete snapshots for VM {vmid}")
        return snapshots

    def observe(self, vmids: list[str], storage: str) -> dict[str, Any]:
        """Atomic, bounded evidence for registered labs; timestamps cover PVE's retained task history."""
        validate_lab_observe(vmids, storage)
        self._require_lab_assets(vmids)
        node_path = f"/nodes/{self.config.node}"
        permissions = self._lab_request("GET", f"/access/permissions?path={quote(node_path, safe='')}", "task permissions")
        node_permissions = permissions.get(node_path) if isinstance(permissions, dict) else None
        # PVE otherwise silently hides other users' tasks, making empty/latest evidence misleading.
        if not isinstance(node_permissions, dict) or node_permissions.get("Sys.Audit") not in (0, 1):
            raise ProxmoxError("Complete task evidence requires Sys.Audit on the configured PVE node")
        vms = []
        for vmid in vmids:
            status, config = self._lab_state(vmid)
            snapshots = self._lab_snapshots(vmid)
            latest: dict[str, int | None] = {}
            for task_type in ("qmstart", "qmrollback"):
                tasks = self._lab_request(
                    "GET", f"{node_path}/tasks?vmid={vmid}&typefilter={task_type}&source=all&limit={LAB_TASK_LIMIT}",
                    f"VM {vmid} {task_type} history",
                )
                if not isinstance(tasks, list) or len(tasks) >= LAB_TASK_LIMIT or any(
                    not isinstance(task, dict) or str(task.get("id")) != vmid or task.get("type") != task_type
                    or type(task.get("starttime")) is not int or task["starttime"] <= 0 for task in tasks
                ):
                    raise ProxmoxError(f"Incomplete or excessive {task_type} history for VM {vmid}")
                latest[task_type] = max((task["starttime"] for task in tasks), default=None)
            vms.append({
                "vmid": int(vmid), "name": status["name"], "status": status["status"], "uptime": status["uptime"],
                "lock": config.get("lock"), "snapshots": sorted(set(snapshots) - {"current"}), "latest_tasks": latest,
            })
        capacity = self._lab_request("GET", f"{node_path}/storage/{storage}/status", "storage status")
        if (
            not isinstance(capacity, dict) or capacity.get("active") != 1 or capacity.get("enabled") != 1
            or any(type(capacity.get(key)) is not int or capacity[key] < 0 for key in ("total", "used", "avail"))
            or capacity["total"] <= 0 or capacity["used"] > capacity["total"] or capacity["avail"] > capacity["total"]
        ):
            raise ProxmoxError("Incomplete or inactive storage capacity")
        return {"vms": vms, "storage": {"name": storage, "total": capacity["total"], "used": capacity["used"], "available": capacity["avail"]}}

    def reset(self, vmid: str, *, name: str, snapshot: str) -> dict[str, Any]:
        """Guard identity, stop, roll back, and prove a stopped guest at the selected snapshot."""
        validate_lab_reset(vmid, name, snapshot)
        self._require_lab_assets([vmid])
        base = f"/nodes/{self.config.node}/qemu/{vmid}"

        def guarded_state() -> dict[str, Any]:
            status, config = self._lab_state(vmid)
            if status["name"] != name or config.get("template") or config.get("lock"):
                raise ProxmoxError(f"VM {vmid} name guard, template or lock check failed")
            return status

        def task(path: str, operation: str, data: dict[str, Any] | None = None) -> None:
            upid = self._lab_request("POST", path, f"VM {vmid} reset {operation}", data=data)
            if not isinstance(upid, str) or not upid.startswith("UPID:"):
                raise ProxmoxError(f"VM {vmid} reset {operation} returned no task identity; inspect before retrying")
            try:
                self.wait_task(upid, timeout_seconds=120)
            except (ProxmoxError, *LAB_TRANSPORT_ERRORS):
                raise ProxmoxError(f"VM {vmid} reset {operation} failed; inspect before retrying") from None
            result = self._lab_request("GET", f"/nodes/{self.config.node}/tasks/{quote(upid, safe='')}/status", f"VM {vmid} reset task result")
            if not isinstance(result, dict) or result.get("status") != "stopped" or result.get("exitstatus") != "OK":
                raise ProxmoxError(f"VM {vmid} reset {operation} has no successful task result; inspect before retrying")

        guarded_state()
        if snapshot not in self._lab_snapshots(vmid):
            raise ProxmoxError(f"VM {vmid} exact snapshot is missing")
        snapshot_config = self._lab_request("GET", f"{base}/snapshot/{snapshot}/config", f"VM {vmid} snapshot config")
        if not isinstance(snapshot_config, dict) or snapshot_config.get("name") != name:
            raise ProxmoxError(f"VM {vmid} snapshot name guard failed")
        guarded_state()
        if snapshot not in self._lab_snapshots(vmid):
            raise ProxmoxError(f"VM {vmid} reset pre-verification failed")
        # PVE checks rollback feasibility before stopping the guest itself. A separate stop
        # would leave a running VM down even when rollback submission or preparation is refused.
        task(f"{base}/snapshot/{snapshot}/rollback", "rollback", {"start": 0})
        # PVE automatically resumes snapshots with RAM, even when start=0.
        if guarded_state()["status"] == "running":
            task(f"{base}/status/stop", "final stop")
        final = guarded_state()
        snapshots = self._lab_snapshots(vmid)
        if final["status"] != "stopped" or snapshot not in snapshots or snapshots["current"].get("parent") != snapshot:
            raise ProxmoxError(f"VM {vmid} reset post-verification failed")
        return {"vmid": int(vmid), "name": name, "snapshot": snapshot, "status": "stopped"}

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

    def start(self, vmid: str, *, lab_hours: float = 4.0, lab_reason: str = "", declare_lab: bool = True) -> None:
        # PVE accepts the request before checking state; the task says whether it ran ("already running" fails it).
        self.wait_task(str(self.request("POST", f"/nodes/{self.config.node}/{self._kind(vmid)}/{vmid}/status/start")), timeout_seconds=120)
        if declare_lab:
            declare_if_lab(vmid, lab_hours, lab_reason)

    def stop(self, vmid: str) -> None:
        self.wait_task(str(self.request("POST", f"/nodes/{self.config.node}/{self._kind(vmid)}/{vmid}/status/stop")), timeout_seconds=120)

    def shutdown(self, vmid: str, timeout_seconds: int = 180) -> None:
        """Clean guest shutdown; the task fails, leaving the guest running, if it is not down in time (never force-stops)."""
        path = f"/nodes/{self.config.node}/{self._kind(vmid)}/{vmid}/status/shutdown"
        self.wait_task(str(self.request("POST", path, data={"timeout": timeout_seconds})), timeout_seconds=timeout_seconds + 30)

    def reboot(self, vmid: str) -> None:
        """Guest shutdown then start; PVE applies pending hardware changes (cores, memory) on the way back up."""
        self.wait_task(str(self.request("POST", f"/nodes/{self.config.node}/{self._kind(vmid)}/{vmid}/status/reboot")), timeout_seconds=300)

    def resize(self, vmid: str, *, cores: int | None = None, memory_mb: int | None = None, balloon_mb: int | None = None) -> bool:
        """Set CPU cores and/or memory; True when the VM is running and the change waits for a reboot."""
        kind = self._kind(vmid)
        data: dict[str, Any] = {}
        if cores is not None:
            data["cores"] = cores
        if memory_mb is not None:
            data["memory"] = memory_mb
        if balloon_mb is not None and kind == "qemu":
            data["balloon"] = balloon_mb
        if not data:
            raise ProxmoxError("Nothing to change: pass cores and/or memory")
        self.request("PUT", f"/nodes/{self.config.node}/{kind}/{vmid}/config", data=data)
        return kind == "qemu" and self.status(vmid).get("status") == "running"

    def grow_disk(self, vmid: str, *, disk: str, add_gib: int) -> None:
        """Add whole GiB to a configured data disk; guest filesystem growth is separate."""
        if not isinstance(disk, str) or not re.fullmatch(r"(?:scsi|sata|virtio|ide)[0-9]+", disk):
            raise ProxmoxError("Use a configured disk slot")
        if type(add_gib) is not int or add_gib < 1:
            raise ProxmoxError("Disk growth requires a positive whole number of GiB")
        value = str(self.config_get(vmid).get(disk, ""))
        if not value or "media=cdrom" in value or "cloudinit" in value:
            raise ProxmoxError("Selected slot is not a data disk")
        self.request("PUT", f"/nodes/{self.config.node}/qemu/{vmid}/resize", data={"disk": disk, "size": f"+{add_gib}G"})

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
