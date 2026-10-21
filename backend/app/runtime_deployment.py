"""Project-catalog placement and native units inside Proxmox guests.

Uses the owner's existing SSH access and QEMU guest agent. Destinations,
credentials, guest type and service-manager scope are catalog/config data.
"""
from __future__ import annotations

import json
import re
import shlex
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

from .utils import safe_subprocess
from .utils.env import float_env

_TIMEOUT = float_env("SUMMITFLOW_REMOTE_UNIT_TIMEOUT", 15.0)
_CONNECT_TIMEOUT = float_env("SUMMITFLOW_REMOTE_UNIT_CONNECT_TIMEOUT", 5.0)


class DeploymentError(RuntimeError):
    """Placement is invalid or the configured guest could not be inspected."""


@dataclass(frozen=True)
class ProxmoxDeployment:
    kind: str
    ssh_host: str
    vmid: int
    user: str = ""
    uid: int = 0
    guest_type: str = "qemu"
    manager: str = "user"

    @property
    def label(self) -> str:
        return f"{self.ssh_host} / {'CT' if self.guest_type == 'lxc' else 'VM'} {self.vmid}"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_deployment(value: Any) -> ProxmoxDeployment | None:
    """Missing placement retains local behavior; malformed placement never does."""
    if value is None:
        return None
    if (not isinstance(value, Mapping) or not {"kind", "ssh_host", "vmid"} <= set(value)
            or set(value) - {"kind", "ssh_host", "vmid", "user", "uid", "guest_type", "manager"}
            or value.get("kind") != "proxmox"
            or not isinstance(value.get("ssh_host"), str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value["ssh_host"])
            or type(value.get("vmid")) is not int or value["vmid"] < 100
            or value.get("guest_type", "qemu") not in ("qemu", "lxc")
            or value.get("manager", "user") not in ("user", "system")):
        raise DeploymentError("runtime.deployment requires proxmox kind, SSH host, guest id and manager")
    target = ProxmoxDeployment(**value)
    if (not isinstance(target.user, str) or type(target.uid) is not int
            or (target.manager == "user" and (not re.fullmatch(r"[a-z_][a-z0-9_-]*", target.user) or target.uid < 1))):
        raise DeploymentError("User-manager placement requires a valid guest user and uid")
    return target


def _ssh(target: ProxmoxDeployment, command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    try:
        return safe_subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", f"ConnectTimeout={max(1, int(_CONNECT_TIMEOUT))}", "-o", "StrictHostKeyChecking=yes",
             target.ssh_host, shlex.join(command)], capture_output=True, text=True, timeout=_TIMEOUT + _CONNECT_TIMEOUT, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DeploymentError(f"Could not reach {target.label}") from exc


def _guest_status(target: ProxmoxDeployment) -> str:
    result = _ssh(target, ["pct" if target.guest_type == "lxc" else "qm", "status", str(target.vmid)])
    status = result.stdout.strip().removeprefix("status: ")
    if result.returncode or status not in {"running", "stopped"}:
        raise DeploymentError(f"Could not inspect {target.label}")
    return status


def _guest_command(target: ProxmoxDeployment, command: list[str]) -> str:
    if target.manager == "user":
        command = ["runuser", "-u", target.user, "--", "env", f"XDG_RUNTIME_DIR=/run/user/{target.uid}",
                   f"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{target.uid}/bus", *command]
    if target.guest_type == "lxc":
        result = _ssh(target, ["pct", "exec", str(target.vmid), "--", *command])
        payload = {"exited": 1, "exitcode": result.returncode, "out-data": result.stdout}
    else:
        result = _ssh(target, ["qm", "guest", "exec", str(target.vmid), "--timeout", str(int(_TIMEOUT)), "--", *command])
        try:
            payload = json.loads(result.stdout) if result.returncode == 0 else {}
        except ValueError as exc:
            raise DeploymentError(f"Could not inspect units on {target.label}") from exc
    # `show` can return nonzero for missing units while returning their state.
    if not isinstance(payload, dict):
        raise DeploymentError(f"Guest command failed on {target.label}")
    output = payload.get("out-data", "")
    if (not isinstance(output, str) or not payload.get("exited") or (payload.get("exitcode") != 0
            and not ("show" in command and "LoadState=not-found" in output))):
        raise DeploymentError(f"Guest command failed on {target.label}")
    return output


def _systemctl(target: ProxmoxDeployment, verb: str, units: Sequence[str]) -> str:
    if not units or any(not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.@:-]*", unit) for unit in units):
        raise DeploymentError("Remote unit operations require declared systemd unit names")
    command = ["systemctl", "--no-ask-password", *(["--user"] if target.manager == "user" else []), verb]
    if verb == "show":
        command += ["--property=Id,LoadState,ActiveState,SubState,UnitFileState,MainPID,ExecMainStatus"]
    return _guest_command(target, [*command, "--", *units])


def unit_states(target: ProxmoxDeployment, units: Sequence[str]) -> dict[str, dict[str, str]]:
    """Read all requested units in one guest call, without process environments."""
    if _guest_status(target) == "stopped":
        return {unit: {"ActiveState": "inactive", "SubState": "guest-stopped", "Error": "Guest is stopped"} for unit in units}
    output = _systemctl(target, "show", units)
    states = {}
    for block in output.strip().split("\n\n"):
        row = dict(line.split("=", 1) for line in block.splitlines() if "=" in line)
        if row.get("Id") in units:
            states[row["Id"]] = row
    return states


def control_units(target: ProxmoxDeployment, action: str, units: Sequence[str]) -> None:
    if action not in {"start", "stop", "restart", "enable", "disable"}:
        raise DeploymentError("Unsupported remote unit action")
    _systemctl(target, action, units)


def recent_logs(target: ProxmoxDeployment, unit: str, tail: int) -> str:
    return _guest_command(target, ["journalctl", *(["--user"] if target.manager == "user" else []),
                                   "-u", unit, "-n", str(tail), "--output=short-iso", "--no-pager"])
