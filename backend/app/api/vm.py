"""Proxmox VM operations for `st vm` callers that hold no Proxmox token (agents); the backend's token does the work.

A pass-through: the token's own PVE rights decide what is allowed (lab pool full, ops pool power + cores/memory,
power pool power, everything else read-only), and PVE errors come back unchanged.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from cli.lib.proxmox import ProxmoxClient, ProxmoxError
from cli.lib.vm_clone import run_clone

from ..access_control import require_authenticated

router = APIRouter(dependencies=[Depends(require_authenticated)])

# ProxmoxClient methods `st vm` uses, with the keyword arguments each accepts
_VMID_OPS: dict[str, tuple[str, ...]] = {
    "status": (),
    "snapshots": (),
    "ip_addresses": (),
    "snapshot": ("name", "description"),
    "rollback": ("snapshot_name",),
    "start": (),
    "stop": (),
    "shutdown": ("timeout_seconds",),
    "reboot": (),
    "resize": ("cores", "memory_mb", "balloon_mb"),
    "destroy": (),
    "monitor": ("command",),
    "sendkey": ("keys",),
    "agent_exec": ("command",),
    "agent_exec_status": ("pid",),
    "config_get": (),
}


class VmOp(BaseModel):
    op: str
    vmid: str | None = None
    args: dict[str, Any] = Field(default_factory=dict)


def run_vm_op(client: ProxmoxClient, body: VmOp) -> Any:
    if body.op == "list_vms":
        return client.list_vms()
    if body.op == "clone":
        lines: list[str] = []
        run_clone(
            client,
            str(body.args["template"]),
            str(body.args["newid"]),
            str(body.args["name"]),
            clone_only=bool(body.args.get("clone_only")),
            progress=lines.append,
        )
        return lines
    allowed = _VMID_OPS.get(body.op)
    if allowed is None or not body.vmid or set(body.args) - set(allowed):
        raise HTTPException(status_code=400, detail=f"Unsupported VM operation: {body.op}")
    kwargs = {key: value for key, value in body.args.items() if value is not None}
    if body.op == "start":
        kwargs["declare_lab"] = False  # the caller declares its own Nightshift lab use
    return getattr(client, body.op)(body.vmid, **kwargs)


@router.post("/vm/op")
def vm_op(body: VmOp) -> dict[str, Any]:
    try:
        return {"result": run_vm_op(ProxmoxClient(), body)}
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=f"Missing argument: {exc}") from exc
    except ProxmoxError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
