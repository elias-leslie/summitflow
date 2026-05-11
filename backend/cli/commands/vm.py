"""Canonical VM operations command surface."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

import typer

from ..lib.confirm_token import confirm_gate
from ..lib.proxmox import ProxmoxClient, ProxmoxError, snapshot_name_default
from ..lib.usage import usage
from ..output import output_error

app = typer.Typer(
    help=(
        "Proxmox VM lifecycle through st. Use for browser/test VM status, IPs, "
        "snapshots, start/stop, rollback, and clone. Destructive actions use "
        "two-pass confirmation gates. For browser work, st browser uses the default "
        "browser VM; use st vm list/status/ip/start only when changing or repairing it."
    ),
)


def _confirm(command_key: str, confirm: str | None, command_hint: str, preview_lines: list[str]) -> None:
    confirm_gate(command_key, confirm, preview_lines, command_hint)


def _client() -> ProxmoxClient:
    try:
        return ProxmoxClient()
    except ProxmoxError as exc:
        output_error(str(exc))
        raise typer.Exit(1) from None


def _run(action) -> None:
    try:
        action(_client())
    except ProxmoxError as exc:
        output_error(str(exc))
        raise typer.Exit(1) from None


def _mb(value: object) -> str:
    try:
        return f"{int(float(str(value))) // 1024 // 1024}MB"
    except (TypeError, ValueError):
        return "0MB"


def _gb(value: object) -> str:
    try:
        return f"{int(float(str(value))) // 1024 // 1024 // 1024}GB"
    except (TypeError, ValueError):
        return "0GB"


@app.command("list")
def list_vms() -> None:
    """List all configured Proxmox test VMs."""
    def action(client: ProxmoxClient) -> None:
        print(f"{'VMID':<6} {'NAME':<25} {'STATUS':<10} {'RAM':<8} {'DISK':<8}")
        print(f"{'----':<6} {'----':<25} {'------':<10} {'---':<8} {'----':<8}")
        for vm in client.list_vms():
            print(
                f"{vm.get('vmid', '')!s:<6} "
                f"{vm.get('name', '')!s:<25} "
                f"{vm.get('status', '')!s:<10} "
                f"{_mb(vm.get('maxmem')):<8} "
                f"{_gb(vm.get('maxdisk')):<8}"
            )

    _run(action)


@app.command()
@usage(
    surface="st.vm.status",
    cmd="st vm status <id>",
    when="inspect browser/test VM state when changing or repairing it",
    precautions=("for routine browser work use st browser, not st vm",),
    task_types=("devops", "verification"),
    tier="reference",
)
def status(vmid: Annotated[str, typer.Argument(help="VM ID")]) -> None:
    """Show VM status."""
    def action(client: ProxmoxClient) -> None:
        data = client.status(vmid)
        cpu = int(float(data.get("cpu") or 0) * 100)
        mem = _mb(data.get("mem"))
        maxmem = _mb(data.get("maxmem"))
        print(
            f"VM {data.get('vmid', vmid)} ({data.get('name', '?')}): "
            f"{data.get('status', '?')} | CPU: {cpu}% | RAM: {mem}/{maxmem} | "
            f"Uptime: {data.get('uptime', 0)}s"
        )

    _run(action)


@app.command()
def snapshots(vmid: Annotated[str, typer.Argument(help="VM ID")]) -> None:
    """List VM snapshots."""
    def action(client: ProxmoxClient) -> None:
        print(f"{'NAME':<30} {'DESCRIPTION':<40} {'CREATED':<25}")
        print(f"{'----':<30} {'-----------':<40} {'-------':<25}")
        for snap in client.snapshots(vmid):
            created = "-"
            if snap.get("snaptime"):
                created = datetime.fromtimestamp(int(snap["snaptime"]), UTC).isoformat()
            print(
                f"{snap.get('name', '')!s:<30} "
                f"{snap.get('description') or '-'!s:<40} "
                f"{created:<25}"
            )

    _run(action)


@app.command()
def ip(vmid: Annotated[str, typer.Argument(help="VM ID")]) -> None:
    """Show VM IP from guest agent."""
    _run(lambda client: print("\n".join(client.ip_addresses(vmid))))


@app.command()
def snapshot(
    vmid: Annotated[str, typer.Argument(help="VM ID")],
    name: Annotated[str | None, typer.Argument(help="Snapshot name")] = None,
) -> None:
    """Create a VM snapshot."""
    snapshot_name = name or snapshot_name_default()

    def action(client: ProxmoxClient) -> None:
        print(f"Creating snapshot '{snapshot_name}' on VM {vmid}...")
        client.snapshot(vmid, snapshot_name, f"Auto-snapshot {datetime.now(UTC).isoformat()}")
        print(f"Done: {snapshot_name}")

    _run(action)


@app.command()
def clone(
    template: Annotated[str, typer.Argument(help="Template VM ID")],
    newid: Annotated[str, typer.Argument(help="New VM ID")],
    name: Annotated[str | None, typer.Argument(help="New VM name")] = None,
) -> None:
    """Clone a VM from a template."""
    vm_name = name or "test-" + datetime.now(UTC).strftime("%Y%m%d-%H%M%S")

    def action(client: ProxmoxClient) -> None:
        print(f"Cloning template {template} -> VM {newid} ({vm_name})...")
        client.clone(template, newid, vm_name)
        print(f"Done: VM {newid}")

    _run(action)


@app.command()
def start(vmid: Annotated[str, typer.Argument(help="VM ID")]) -> None:
    """Start a VM."""
    _run(lambda client: (client.start(vmid), print(f"VM {vmid} starting")))


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
    _run(lambda client: (client.stop(vmid), print(f"VM {vmid} stopping")))


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
    def action(client: ProxmoxClient) -> None:
        print(f"Rolling back VM {vmid} to snapshot '{snapshot_name}'...")
        client.rollback(vmid, snapshot_name)
        print("Done")

    _run(action)


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
    _run(lambda client: (client.destroy(vmid), print(f"VM {vmid} destroyed")))
