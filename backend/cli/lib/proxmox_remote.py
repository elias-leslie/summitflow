"""`st vm` without a local Proxmox token: the same client calls, run by the backend route that holds the token."""

from __future__ import annotations

import os
from typing import Any

from ..client import APIError, STClient
from .proxmox import (
    ADMIN_TOKEN_ENV,
    LAB_TRANSPORT_ERRORS,
    ProxmoxError,
    declare_if_lab,
    validate_lab_observation,
    validate_lab_observe,
    validate_lab_reset,
)

# Clone/provision/boot can take minutes; the route returns once the guest is ready
_TIMEOUT_SECONDS = 900.0
ADMIN_TOKEN_HEADER = "X-Proxmox-Admin-Token"
_LAB_SCOPE = object()


class RemoteProxmoxClient:
    """Mirrors the ProxmoxClient methods `st vm` uses; each call is one POST /api/vm/op."""

    def __init__(self, http: Any = None, *, allow_admin_token: bool = True) -> None:
        self._http = http or STClient(require_project=False, timeout=_TIMEOUT_SECONDS)
        self.__lab_scope: object | None = None
        if not allow_admin_token and (http_client := getattr(self._http, "_client", None)) is not None:
            http_client.headers.pop(ADMIN_TOKEN_HEADER, None)
        if allow_admin_token and (admin_token := os.environ.get(ADMIN_TOKEN_ENV, "").strip()):
            self._http._client.headers[ADMIN_TOKEN_HEADER] = admin_token

    @property
    def _lab_scoped(self) -> bool:
        return self.__lab_scope is _LAB_SCOPE

    @classmethod
    def for_lab(cls, http: Any = None) -> RemoteProxmoxClient:
        """Construct a backend route client without forwarding owner elevation."""
        try:
            client = cls(http, allow_admin_token=False)
        except (ProxmoxError, *LAB_TRANSPORT_ERRORS):
            raise ProxmoxError("Proxmox backend route unavailable; no complete result") from None
        client.__lab_scope = _LAB_SCOPE
        return client

    def _call(self, op: str, vmid: str | None = None, *, _safe_errors: bool = False, **args: Any) -> Any:
        if op in {"observe", "reset"} and not self._lab_scoped:
            raise ProxmoxError("Lab operations require an unelevated RemoteProxmoxClient.for_lab()")
        try:
            response = self._http.post(self._http._global_url("/vm/op"), json={"op": op, "vmid": vmid, "args": args})
        except APIError as exc:
            if _safe_errors:
                raise ProxmoxError(f"Proxmox {op} refused or incomplete; no complete result") from None
            detail = exc.detail.get("message") if isinstance(exc.detail, dict) else exc.detail  # the app's error envelope
            raise ProxmoxError(str(detail)) from exc
        except Exception as exc:  # legacy calls retain their broad backend error contract
            if _safe_errors:
                if not isinstance(exc, LAB_TRANSPORT_ERRORS):
                    raise
                raise ProxmoxError("Proxmox backend route unavailable; no complete result") from None
            raise ProxmoxError(f"Proxmox backend route failed: {exc}") from exc
        if _safe_errors and not isinstance(response, dict):
            raise ProxmoxError("Proxmox backend route returned no complete result")
        return response.get("result")

    def observe(self, vmids: list[str], storage: str) -> dict[str, Any]:
        validate_lab_observe(vmids, storage)
        result = self._call("observe", vmids=vmids, storage=storage, _safe_errors=True)
        validate_lab_observation(result, vmids, storage)
        return result

    def reset(self, vmid: str, *, name: str, snapshot: str) -> dict[str, Any]:
        validate_lab_reset(vmid, name, snapshot)
        result = self._call("reset", vmid, name=name, snapshot=snapshot, _safe_errors=True)
        if result != {"vmid": int(vmid), "name": name, "snapshot": snapshot, "status": "stopped"}:
            raise ProxmoxError("Proxmox reset returned no verified result; inspect before retrying")
        return result

    def list_vms(self) -> list[dict[str, Any]]:
        return self._call("list_vms")

    def status(self, vmid: str) -> dict[str, Any]:
        return self._call("status", vmid)

    def snapshots(self, vmid: str) -> list[dict[str, Any]]:
        return self._call("snapshots", vmid)

    def ip_addresses(self, vmid: str) -> list[str]:
        return self._call("ip_addresses", vmid)

    def snapshot(self, vmid: str, name: str, description: str) -> None:
        self._call("snapshot", vmid, name=name, description=description)

    def rollback(self, vmid: str, snapshot_name: str) -> None:
        self._call("rollback", vmid, snapshot_name=snapshot_name)

    def start(self, vmid: str, *, lab_hours: float = 4.0, lab_reason: str = "") -> None:
        self._call("start", vmid)
        declare_if_lab(vmid, lab_hours, lab_reason)  # nightshift lab-use runs as the caller, like the direct path

    def stop(self, vmid: str) -> None:
        self._call("stop", vmid)

    def shutdown(self, vmid: str, timeout_seconds: int = 180) -> None:
        self._call("shutdown", vmid, timeout_seconds=timeout_seconds)

    def reboot(self, vmid: str) -> None:
        self._call("reboot", vmid)

    def resize(self, vmid: str, *, cores: int | None = None, memory_mb: int | None = None, balloon_mb: int | None = None) -> bool:
        return bool(self._call("resize", vmid, cores=cores, memory_mb=memory_mb, balloon_mb=balloon_mb))

    def destroy(self, vmid: str) -> None:
        self._call("destroy", vmid)

    def monitor(self, vmid: str, command: str) -> str:
        return self._call("monitor", vmid, command=command)

    def sendkey(self, vmid: str, keys: str) -> None:
        self._call("sendkey", vmid, keys=keys)

    def agent_exec(self, vmid: str, command: list[str] | str) -> dict[str, Any]:
        return self._call("agent_exec", vmid, command=command)

    def agent_exec_status(self, vmid: str, pid: int) -> dict[str, Any]:
        return self._call("agent_exec_status", vmid, pid=pid)

    def config_get(self, vmid: str) -> dict[str, Any]:
        return self._call("config_get", vmid)

    def run_clone(self, template: str, newid: str, name: str, *, clone_only: bool) -> list[str]:
        """Progress lines of the server-side clone (printed after it finishes, not streamed)."""
        return self._call("clone", template=template, newid=newid, name=name, clone_only=clone_only)
