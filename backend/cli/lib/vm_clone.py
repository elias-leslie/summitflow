"""Managed Linux clones: explicit public access before boot, proven readiness after it."""

from __future__ import annotations

import base64
import ipaddress
import math
import os
import re
import struct
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from urllib.parse import quote

from app.utils.shared_paths import get_repo_root

from .proxmox import ProxmoxClient, ProxmoxError, ProxmoxTaskError, _read_env_file


class ClonePhase(StrEnum):
    PREFLIGHT = "preflight"
    COPY = "copy"
    CONFIGURE = "configure"
    START = "start"
    READY = "readiness"


class ManagedCloneError(ProxmoxError):
    def __init__(self, vmid: str, phase: ClonePhase, reason: str, upid: str | None = None) -> None:
        self.vmid, self.phase, self.upid = vmid, phase, upid
        recovery = (
            "No copy submitted; correct the profile/template and retry."
            if phase == ClonePhase.PREFLIGHT
            else f"VM {vmid} retained; inspect st vm status {vmid}, st vm config {vmid}, and the task. "
            "Use verified exec-ssh/repair-agent recovery if needed; do not blindly reclone or delete."
        )
        super().__init__(f"VM {vmid} phase={phase} task={upid or 'not-returned'}: {reason}. {recovery}")


@dataclass(frozen=True)
class CloneAccessProfile:
    """An owner-selected, qualified template and public-only cloud-init access."""

    template: str
    user: str
    public_keys: str = field(repr=False)
    ipconfig0: str = "ip=dhcp"
    timeout_seconds: float = 300


@dataclass(frozen=True)
class ReadyClone:
    vmid: str
    upid: str
    addresses: tuple[str, ...]


def _public_keys(path: Path) -> str:
    try:
        if path.stat().st_size > 65536:
            raise ValueError
        text = path.read_text()
        if "PRIVATE KEY" in text:
            raise ValueError
        keys = []
        for line in text.splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            parts = line.split()
            if len(parts) < 2 or parts[0] not in {"ssh-ed25519", "ssh-rsa", "ecdsa-sha2-nistp256", "ecdsa-sha2-nistp384", "ecdsa-sha2-nistp521"}:
                raise ValueError
            blob = base64.b64decode(parts[1], validate=True)
            fields = []
            while blob:
                size = struct.unpack(">I", blob[:4])[0]
                if size <= 0 or size > len(blob) - 4:
                    raise ValueError
                fields.append(blob[4:4 + size])
                blob = blob[4 + size:]
            if not fields or fields[0].decode() != parts[0]:
                raise ValueError
            if parts[0] == "ssh-ed25519" and (len(fields) != 2 or len(fields[1]) != 32):
                raise ValueError
            if parts[0] == "ssh-rsa" and len(fields) != 3:
                raise ValueError
            if parts[0].startswith("ecdsa-") and len(fields) != 3:
                raise ValueError
            # Comments/options are deliberately not forwarded to Proxmox.
            keys.append(" ".join(parts[:2]))
        if not keys:
            raise ValueError
        return "\n".join(keys)
    except (OSError, ValueError, UnicodeError, struct.error) as exc:
        raise ProxmoxError("PROXMOX_CLONE_PUBLIC_KEY_FILE must contain valid public SSH keys, never private material") from exc


def load_clone_access_profile() -> CloneAccessProfile:
    values = _read_env_file(get_repo_root() / "docker" / "compose" / ".env")

    def value(name: str) -> str:
        return os.environ.get(name, values.get(name, "")).strip()

    template, user, keyfile = (value(name) for name in (
        "PROXMOX_CLONE_TEMPLATE", "PROXMOX_CLONE_USER", "PROXMOX_CLONE_PUBLIC_KEY_FILE",
    ))
    if not template or not user or not keyfile:
        raise ProxmoxError("Configure PROXMOX_CLONE_TEMPLATE, PROXMOX_CLONE_USER, and PROXMOX_CLONE_PUBLIC_KEY_FILE explicitly")
    if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", user) or user == "root":
        raise ProxmoxError("PROXMOX_CLONE_USER must be a non-root Linux account name")
    network = value("PROXMOX_CLONE_IPCONFIG0") or "ip=dhcp"
    # Deliberately small profile: DHCP or an explicit IPv4 address and gateway.
    if network != "ip=dhcp":
        try:
            match = re.fullmatch(r"ip=([^,]+),gw=([^,]+)", network)
            if not match:
                raise ValueError
            interface = ipaddress.IPv4Interface(match[1])
            gateway = ipaddress.IPv4Address(match[2])
            if gateway not in interface.network or not _usable(str(interface.ip)):
                raise ValueError
        except ValueError as exc:
            raise ProxmoxError("PROXMOX_CLONE_IPCONFIG0 must be ip=dhcp or ip=IPv4/CIDR,gw=IPv4") from exc
    try:
        timeout = float(value("PROXMOX_CLONE_READY_TIMEOUT") or "300")
        if not math.isfinite(timeout) or not 1 <= timeout <= 1800:
            raise ValueError
    except ValueError as exc:
        raise ProxmoxError("PROXMOX_CLONE_READY_TIMEOUT must be between 1 and 1800 seconds") from exc
    return CloneAccessProfile(template, user, _public_keys(Path(keyfile)), network, timeout)


def _usable(address: str) -> bool:
    try:
        ip = ipaddress.IPv4Address(address)
        return not (ip.is_loopback or ip.is_link_local or ip.is_unspecified or ip.is_multicast or ip.is_reserved)
    except ValueError:
        return False


def managed_clone(
    client: ProxmoxClient,
    template: str,
    newid: str,
    name: str,
    *,
    profile: CloneAccessProfile | None = None,
    progress: Callable[[str], None] = lambda message: print(message, flush=True),
) -> ReadyClone:
    """Own the complete clone workflow; retain phase/task/VM identity on every failure."""
    phase, upid = ClonePhase.PREFLIGHT, None
    try:
        profile = profile or load_clone_access_profile()
        if not all(re.fullmatch(r"[1-9][0-9]*", identity) for identity in (template, newid)) or template == newid:
            raise ProxmoxError("Use distinct numeric template and destination VM IDs")
        if not re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?", name):
            raise ProxmoxError("Use a hostname without dots, spaces, or shell options")
        if template != profile.template:
            raise ProxmoxError("Template differs from the owner's qualified PROXMOX_CLONE_TEMPLATE; qualify it or use --clone-only")
        if any(str(item.get("vmid")) == newid for item in client.list_vms()):
            raise ProxmoxError("Destination VM ID already exists")
        cfg = client.config_get(template)
        if not cfg.get("template") or cfg.get("ostype") != "l26":
            raise ProxmoxError("Managed readiness requires a Linux template; use --clone-only for Windows/unsupported images")
        if not any("cloudinit" in str(value) for key, value in cfg.items() if re.fullmatch(r"(?:ide|sata|scsi)[0-9]+", key)) or not cfg.get("net0"):
            raise ProxmoxError("Qualified template requires a cloud-init drive and net0")
        if cfg.get("cicustom"):
            raise ProxmoxError("Custom cloud-init snippets may override owner access; qualify a standard cloud-init template")
        phase = ClonePhase.COPY
        progress(f"Copying template {template} -> VM {newid} ({name})...")
        upid = client.clone(template, newid, name)
        progress(f"Copy complete: VM {newid} task={upid}; configuring guest access before boot...")
        phase = ClonePhase.CONFIGURE
        destination = client.config_get(newid)
        if destination.get("template") or destination.get("name") != name:
            raise ProxmoxError("Destination identity differs from the requested non-template guest")
        access = {"ciuser": profile.user, "sshkeys": quote(profile.public_keys, safe=""), "ipconfig0": profile.ipconfig0, "agent": "enabled=1", "ciupgrade": "0", "delete": "cipassword"}
        if destination.get("digest"):
            access["digest"] = destination["digest"]
        client.config_update(newid, access)
        phase = ClonePhase.START
        progress(f"Starting VM {newid}; waiting for guest execution and usable IPv4...")
        client.start(newid)
        phase = ClonePhase.READY
        deadline, pid = time.monotonic() + profile.timeout_seconds, None
        while time.monotonic() < deadline:
            try:
                if pid is None:
                    # Hostname binds execution to the intended cloud-init identity;
                    # cloud-init completion proves first-boot access provisioning.
                    # New cloud-init returns 2 for Proxmox's deprecated `user`
                    # schema even when provisioned correctly. Accept deprecation
                    # notices only, never failed or other degraded provisioning.
                    probe = (
                        'test "$(hostname -s)" = "$1" && '
                        '(systemctl is-active --quiet ssh.service || systemctl is-active --quiet sshd.service || systemctl is-active --quiet ssh.socket) && '
                        'cloud-init status --wait --format json | python3 -c '
                        "'import json,sys; s=json.load(sys.stdin); sys.exit(0 if s.get(\"status\")==\"done\" and not s.get(\"errors\") and all(k==\"DEPRECATED\" for k in s.get(\"recoverable_errors\",{})) else 1)'"
                    )
                    execution = client.agent_exec(newid, ["/bin/sh", "-c", probe, "st-clone-ready", name])
                    pid = execution.get("pid")
                    if not isinstance(pid, int):
                        raise ProxmoxError("Guest exec returned no process ID")
                status = client.agent_exec_status(newid, pid)
                if status.get("exited"):
                    if status.get("exitcode") != 0:
                        raise ManagedCloneError(newid, phase, "Guest identity, SSH daemon, or cloud-init qualification failed", upid)
                    addresses = tuple(address for address in client.ip_addresses(newid) if _usable(address))
                    if addresses:
                        progress(f"Guest ready: VM {newid} IPv4={','.join(addresses)} task={upid}")
                        return ReadyClone(newid, upid, addresses)
            except ManagedCloneError:
                raise
            except ProxmoxError:
                pass  # Agent availability during boot is transient; wait within the bound.
            time.sleep(min(2, max(0, deadline - time.monotonic())))
        raise ManagedCloneError(newid, phase, "Timed out waiting for verified guest execution and usable IPv4", upid)
    except ManagedCloneError:
        raise
    except ProxmoxTaskError as exc:
        raise ManagedCloneError(newid, phase, "Copy failed or timed out", exc.upid) from exc
    except ProxmoxError as exc:
        # Only preflight text is safe to echo. Config/API errors may reflect keys.
        reason = str(exc) if phase == ClonePhase.PREFLIGHT else "Proxmox operation failed; inspect the retained VM/task"
        raise ManagedCloneError(newid, phase, reason, upid) from exc
