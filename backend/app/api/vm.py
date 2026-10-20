"""Proxmox VM operations for `st vm` callers that hold no Proxmox token (agents); the backend's token does the work.

A pass-through (an `X-Proxmox-Admin-Token` header swaps in the elevated token for that request): the token's own PVE rights decide what is allowed (lab pool full, ops pool power + cores/memory,
power pool power, everything else read-only), and PVE errors come back unchanged.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from cli.lib.proxmox import (
    LAB_OPERATION_ERRORS,
    ProxmoxClient,
    ProxmoxError,
    parse_admin_token,
    validate_lab_observe,
    validate_lab_reset,
)
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
    if body.op == "observe":
        if body.vmid is not None or set(body.args) != {"vmids", "storage"}:
            raise HTTPException(status_code=400, detail="Observe requires only explicit vmids and storage")
        validate_lab_observe(body.args["vmids"], body.args["storage"])
        return client.observe(**body.args)
    if body.op == "reset":
        if not body.vmid or set(body.args) != {"name", "snapshot"}:
            raise HTTPException(status_code=400, detail="Reset requires only exact name and snapshot")
        validate_lab_reset(body.vmid, body.args["name"], body.args["snapshot"])
        return client.reset(body.vmid, **body.args)
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


def request_client(admin_token: str | None) -> ProxmoxClient:
    """The backend's client; with an elevated token header (Nightshift's proxmox-admin) its token is swapped in for
    this request only."""
    client = ProxmoxClient()
    if admin_token and admin_token.strip():
        token_id, secret = parse_admin_token(admin_token.strip())
        client = ProxmoxClient(replace(client.config, token_id=token_id, token_secret=secret))
    return client


@router.post("/vm/op")
def vm_op(body: VmOp, x_proxmox_admin_token: Annotated[str | None, Header()] = None) -> dict[str, Any]:
    lab_op = body.op in {"observe", "reset"}
    if lab_op and x_proxmox_admin_token is not None:
        raise HTTPException(status_code=400, detail="Lab operations do not accept elevated credentials")
    try:
        try:
            client = ProxmoxClient.for_lab() if lab_op else request_client(x_proxmox_admin_token)
        except LAB_OPERATION_ERRORS:
            if lab_op:
                raise ProxmoxError("Proxmox client unavailable; check configured API access") from None
            raise
        return {"result": run_vm_op(client, body)}
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=f"Missing argument: {exc}") from exc
    except ProxmoxError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LAB_OPERATION_ERRORS:
        if lab_op:
            raise HTTPException(status_code=400, detail="Proxmox lab operation unavailable; no complete result") from None
        raise
