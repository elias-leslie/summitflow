"""Canonical VM operations command surface."""

from __future__ import annotations

from typing import Annotated

import typer

from ..lib.confirm_token import confirm_gate
from .operator_forward import run_forwarded, run_forwarded_with_input

app = typer.Typer(
    help="Proxmox test VM lifecycle commands with st confirmation gates.",
)


def _confirm(command_key: str, confirm: str | None, command_hint: str, preview_lines: list[str]) -> None:
    confirm_gate(command_key, confirm, preview_lines, command_hint)


@app.command("list")
def list_vms() -> None:
    """List all configured Proxmox test VMs."""
    run_forwarded("proxmox-vm.sh", ["list"])


@app.command()
def status(vmid: Annotated[str, typer.Argument(help="VM ID")]) -> None:
    """Show VM status."""
    run_forwarded("proxmox-vm.sh", ["status", vmid])


@app.command()
def snapshots(vmid: Annotated[str, typer.Argument(help="VM ID")]) -> None:
    """List VM snapshots."""
    run_forwarded("proxmox-vm.sh", ["snapshots", vmid])


@app.command()
def ip(vmid: Annotated[str, typer.Argument(help="VM ID")]) -> None:
    """Show VM IP from guest agent."""
    run_forwarded("proxmox-vm.sh", ["ip", vmid])


@app.command()
def snapshot(
    vmid: Annotated[str, typer.Argument(help="VM ID")],
    name: Annotated[str | None, typer.Argument(help="Snapshot name")] = None,
) -> None:
    """Create a VM snapshot."""
    args = ["snapshot", vmid]
    if name:
        args.append(name)
    run_forwarded("proxmox-vm.sh", args)


@app.command()
def clone(
    template: Annotated[str, typer.Argument(help="Template VM ID")],
    newid: Annotated[str, typer.Argument(help="New VM ID")],
    name: Annotated[str | None, typer.Argument(help="New VM name")] = None,
) -> None:
    """Clone a VM from a template."""
    args = ["clone", template, newid]
    if name:
        args.append(name)
    run_forwarded("proxmox-vm.sh", args)


@app.command()
def start(vmid: Annotated[str, typer.Argument(help="VM ID")]) -> None:
    """Start a VM."""
    run_forwarded("proxmox-vm.sh", ["start", vmid])


@app.command()
def stop(
    vmid: Annotated[str, typer.Argument(help="VM ID")],
    confirm: Annotated[str | None, typer.Option("--confirm", help="Confirm token from preview run")] = None,
) -> None:
    """Stop a VM. Two-pass confirmation required."""
    _confirm(
        f"vm-stop-{vmid}",
        confirm,
        f"st vm stop {vmid}",
        [
            f"STOP VM: {vmid}",
            "This may interrupt running workloads.",
        ],
    )
    run_forwarded("proxmox-vm.sh", ["stop", vmid])


@app.command()
def rollback(
    vmid: Annotated[str, typer.Argument(help="VM ID")],
    snapshot_name: Annotated[str, typer.Argument(help="Snapshot name")],
    confirm: Annotated[str | None, typer.Option("--confirm", help="Confirm token from preview run")] = None,
) -> None:
    """Rollback a VM snapshot. Two-pass confirmation required."""
    _confirm(
        f"vm-rollback-{vmid}-{snapshot_name}",
        confirm,
        f"st vm rollback {vmid} {snapshot_name}",
        [
            f"ROLLBACK VM: {vmid}",
            f"Snapshot: {snapshot_name}",
            "This will discard VM state newer than the snapshot.",
        ],
    )
    run_forwarded("proxmox-vm.sh", ["rollback", vmid, snapshot_name])


@app.command()
def destroy(
    vmid: Annotated[str, typer.Argument(help="VM ID")],
    confirm: Annotated[str | None, typer.Option("--confirm", help="Confirm token from preview run")] = None,
) -> None:
    """Destroy a VM. Two-pass confirmation required."""
    _confirm(
        f"vm-destroy-{vmid}",
        confirm,
        f"st vm destroy {vmid}",
        [
            f"DESTROY VM: {vmid}",
            "This permanently deletes the VM.",
            "Template VM 9000 remains blocked by the underlying runner.",
        ],
    )
    run_forwarded_with_input("proxmox-vm.sh", ["destroy", vmid], "y\n")
