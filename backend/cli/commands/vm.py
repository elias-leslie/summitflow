"""Canonical VM operations command surface."""

from __future__ import annotations

import re
import shlex
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
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


@app.command("monitor")
def monitor(
    vmid: Annotated[str, typer.Argument(help="VM ID")],
    command: Annotated[str, typer.Argument(help="QEMU monitor command string (e.g. 'info mice', 'info status')")],
) -> None:
    """Execute a QEMU monitor command directly on a VM."""
    def action(client: ProxmoxClient) -> None:
        out = client.monitor(vmid, command)
        if out:
            print(out)

    _run(action)


@app.command("sendkey")
def sendkey(
    vmid: Annotated[str, typer.Argument(help="VM ID")],
    keys: Annotated[str, typer.Argument(help="Key combination (e.g., 'shift-f10', 'ctrl-alt-delete', 'ret')")],
) -> None:
    """Send a key combination to a VM."""
    _run(lambda client: (client.sendkey(vmid, keys), print(f"Sent key '{keys}' to VM {vmid}")))


@app.command("exec")
def exec_guest(
    vmid: Annotated[str, typer.Argument(help="VM ID")],
    command: Annotated[str, typer.Argument(help="Shell command to execute in guest")],
    wait: Annotated[bool, typer.Option(help="Wait for completion and return guest output/status")] = False,
) -> None:
    """Execute using the guest OS shell through QEMU guest agent."""
    def action(client: ProxmoxClient) -> None:
        windows = str(client.config_get(vmid).get("ostype", "")).startswith("win")
        argv = ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command] if windows else ["/bin/sh", "-lc", command]
        res = client.agent_exec(vmid, argv)
        pid = res.get("pid")
        if not isinstance(pid, int):
            raise ProxmoxError("Guest exec returned no process ID")
        print(f"Started guest process PID {pid} on VM {vmid}")
        if not wait:
            return
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            status = client.agent_exec_status(vmid, pid)
            if status.get("exited"):
                for key in ("out-data", "err-data"):
                    if status.get(key):
                        print(status[key])
                if status.get("exitcode") != 0:
                    raise ProxmoxError(f"Guest process exited with code {status.get('exitcode')}, signal {status.get('signal')}")
                return
            time.sleep(1)
        raise ProxmoxError(f"Timed out waiting for guest PID {pid}; process may still be running")

    _run(action)


@app.command("config")
def config(
    vmid: Annotated[str, typer.Argument(help="VM ID")],
) -> None:
    """Display VM hardware configuration."""
    def action(client: ProxmoxClient) -> None:
        cfg = client.config_get(vmid)
        for k, v in sorted(cfg.items()):
            print(f"{k:<15} = {v}")

    _run(action)



@app.command("repair-agent")
def repair_agent(
    vmid: Annotated[str, typer.Argument(help="Linux VM ID")],
    ssh_target: Annotated[str, typer.Option(help="Existing SSH user@host for this VM")],
    jump_host: Annotated[str | None, typer.Option(help="Existing SSH jump host alias")] = None,
    identity_file: Annotated[Path | None, typer.Option(help="Existing SSH private-key path")] = None,
    repair_packages: Annotated[bool, typer.Option(help="Repair broken Debian dependencies without removing packages")] = False,
) -> None:
    """Repair a Linux guest agent through verified SSH recovery access."""
    def action(client: ProxmoxClient) -> None:
        if client.config_get(vmid).get("ostype") != "l26":
            raise ProxmoxError("Automatic guest-agent repair requires Linux; use exec-ssh for Windows recovery")
        script = (
            'if [ "$(systemctl show -p LoadState --value qemu-guest-agent)" = not-found ]; then\n'
            "  command -v apt-get >/dev/null || { echo 'Install qemu-guest-agent using the guest package manager' >&2; exit 1; }\n"
            "  sudo -n apt-get update\n"
            "  sudo -n env DEBIAN_FRONTEND=noninteractive apt-get install -y qemu-guest-agent\n"
            "fi\n"
            "sudo -n systemctl restart qemu-guest-agent\n"
            "systemctl is-active qemu-guest-agent\n"
        )
        if repair_packages:
            script = script.replace(
                "  sudo -n apt-get update\n",
                "  sudo -n apt-get update\n  sudo -n env DEBIAN_FRONTEND=noninteractive apt-get --fix-broken --no-remove install -y\n",
            )
        _ssh_guest(client, vmid, ssh_target, script, jump_host, identity_file)

    _run(action)


def _ssh_guest(client, vmid, ssh_target, command, jump_host, identity_file):
    for target in (ssh_target, jump_host):
        if target is not None and not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.@:\[\]-]*", target):
            raise typer.BadParameter("Use an SSH host alias or user@host, without options")
    cfg = client.config_get(vmid)
    windows = str(cfg.get("ostype", "")).startswith("win")
    if windows:
        macs = []
        for key, value in cfg.items():
            if re.fullmatch(r"net[0-9]+", key):
                match = re.search(r"=([0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5})(?:,|$)", str(value))
                if match:
                    macs.append(match.group(1))
        if not macs:
            raise ProxmoxError("Windows SSH recovery requires a configured guest NIC identity")
        literals = ",".join("'" + mac + "'" for mac in macs)
        guard = (
            f"$stGuestMacs = @({literals})\n"
            "$stGuestAdapters = @(Get-NetAdapter -IncludeHidden | Where-Object { $stGuestMacs -contains ($_.MacAddress -replace '-', ':') })\n"
            "if ($stGuestAdapters.Count -eq 0) { throw 'Guest NIC does not match VM configuration' }\n"
        )
        script = "try {\n$ErrorActionPreference = 'Stop'\n" + guard + command + "\n} catch { [Console]::Error.WriteLine($_.Exception.Message); exit 1 }\nexit 0\n\n"
        remote = "powershell.exe -NoProfile -NonInteractive -Command -"
    else:
        if cfg.get("ostype") != "l26" or not cfg.get("name"):
            raise ProxmoxError("SSH recovery requires a named Linux or Windows VM")
        expected = shlex.quote(str(cfg["name"]))
        script = "set -eu\n" + f'test "$(hostname -s)" = {expected} || {{ echo "Guest hostname does not match VM" >&2; exit 1; }}\n' + command
        remote = "sh -s"
    args = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10"]
    if jump_host:
        args.extend(["-J", jump_host])
    if identity_file:
        args.extend(["-i", str(identity_file)])
    args.extend(["--", ssh_target, remote])
    try:
        result = subprocess.run(args, input=script, text=True, capture_output=True, timeout=300)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ProxmoxError(f"SSH guest-agent recovery failed: {exc}") from exc
    if result.returncode:
        raise ProxmoxError((result.stdout + "\n" + result.stderr).strip()[-6000:] or "Guest-agent restart failed")
    print(result.stdout.strip())


@app.command("exec-ssh")
def exec_ssh(
    vmid: Annotated[str, typer.Argument(help="VM ID")],
    command: Annotated[str, typer.Argument(help="Shell command; use - to read stdin")],
    ssh_target: Annotated[str, typer.Option(help="Existing SSH user@host for this VM")],
    jump_host: Annotated[str | None, typer.Option(help="Existing SSH jump host alias")] = None,
    identity_file: Annotated[Path | None, typer.Option(help="Existing SSH private-key path")] = None,
) -> None:
    """Execute through verified SSH when QEMU execution or stdin is unavailable."""
    import sys

    script = sys.stdin.read() if command == "-" else command
    _run(lambda client: _ssh_guest(client, vmid, ssh_target, script, jump_host, identity_file))


@app.command("grow-disk")
def grow_disk(
    vmid: Annotated[str, typer.Argument(help="VM ID")],
    disk: Annotated[str, typer.Argument(help="Configured disk slot, such as scsi0")],
    add_gib: Annotated[int, typer.Argument(min=1, help="GiB to add; shrinking is not supported")],
) -> None:
    """Add capacity to an existing VM disk. Guest filesystem growth is separate."""
    def action(client: ProxmoxClient) -> None:
        if not re.fullmatch(r"(?:scsi|sata|virtio|ide)[0-9]+", disk):
            raise typer.BadParameter("Use a configured disk slot")
        cfg = client.config_get(vmid)
        value = str(cfg.get(disk, ""))
        if not value or "media=cdrom" in value or "cloudinit" in value:
            raise ProxmoxError("Selected slot is not a data disk")
        client.request("PUT", f"/nodes/{client.config.node}/qemu/{vmid}/resize", data={"disk": disk, "size": f"+{add_gib}G"})
        print(f"Added {add_gib} GiB to VM {vmid} {disk}; grow the guest partition and filesystem next")

    _run(action)
