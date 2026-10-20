"""Current-user, loopback-only SSH access to isolated managed lab services."""

from __future__ import annotations

import fcntl
import hashlib
import ipaddress
import json
import os
import re
import signal
import socket
import subprocess
import tempfile
import time
from contextlib import contextmanager, suppress
from pathlib import Path

from app.utils.shared_paths import get_host_config_root

from .proxmox import ProxmoxConfig, ProxmoxError


def _runtime() -> Path:
    base = Path(os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir())
    root = base / f"st-vm-forward-{os.getuid()}"
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    st = root.lstat()
    if root.is_symlink() or st.st_uid != os.getuid() or st.st_mode & 0o077:
        raise ProxmoxError("VM forwarding runtime directory must be private and owned by this user")
    return root


@contextmanager
def _locked():
    root = _runtime()
    with (root / "lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield root


def _lab_networks():
    path = get_host_config_root().parent / "nightshift/deploy/boundary-net/net.json"
    try:
        return [ipaddress.IPv4Network(c) for c in json.loads(path.read_text())["labnet"]["cidrs"]]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ProxmoxError("Cannot load the existing Nightshift labnet CIDRs") from exc


def _guest(client, vmid: str, *, lab: bool) -> tuple[str, dict]:
    if not re.fullmatch(r"[1-9][0-9]*", vmid):
        raise ProxmoxError("Use a numeric managed VM ID")
    row = next((r for r in client.list_vms() if str(r.get("vmid")) == vmid), None)
    cfg = client.config_get(vmid) if row else {}
    if not row or row.get("type") != "qemu" or row.get("status") != "running" or cfg.get("template") or not cfg.get("name"):
        raise ProxmoxError(f"VM {vmid} must be a running, named, non-template managed guest")
    addresses = [ipaddress.IPv4Address(a) for a in client.ip_addresses(vmid)]
    if lab:
        pool = getattr(getattr(client, "config", None), "pool", None) or ProxmoxConfig.pool
        if row.get("pool") != pool:
            raise ProxmoxError(f"VM {vmid} must belong to the managed lab pool")
        networks = _lab_networks()
        addresses = [a for a in addresses if any(a in n for n in networks)]
    addresses = [a for a in addresses if not (a.is_loopback or a.is_unspecified or a.is_link_local or a.is_multicast)]
    if not addresses:
        raise ProxmoxError(f"VM {vmid} has no usable {'labnet ' if lab else ''}IPv4 address")
    return str(addresses[0]), cfg


def _ssh(host: str) -> list[str]:
    # User/identity remain selected by the user's existing scoped SSH configuration.
    return ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-o", "ForwardAgent=no",
            "-o", "ForwardX11=no", "-o", "IdentityAgent=none", "-o", "ControlPath=none", host]


def _remote(host: str, command: str) -> str:
    result = subprocess.run([*_ssh(host), command], capture_output=True, text=True, timeout=20, check=False)
    if result.returncode:
        raise ProxmoxError(f"Scoped SSH to {host} failed: {result.stderr.strip()[-600:]}")
    return result.stdout.strip()


def _verify(host: str, cfg: dict) -> None:
    if _remote(host, "hostname -s") != cfg["name"]:
        raise ProxmoxError(f"SSH guest identity does not match managed VM {cfg['name']}")


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _process(pid: int) -> dict | None:
    try:
        root = Path(f"/proc/{pid}")
        if root.stat().st_uid != os.getuid():
            return None
        fields = (root / "stat").read_text().rsplit(")", 1)[1].split()
        if fields[0] == "Z":
            return None
        argv = (root / "cmdline").read_bytes().rstrip(b"\0").decode().split("\0")
        return {"pid": pid, "start_token": fields[19], "argv": argv}
    except (OSError, ValueError, IndexError):
        return None


def _owned(process: dict) -> bool:
    return _process(process["pid"]) == process


def _stop(process: dict) -> None:
    # A reused PID, changed command, or another user's process never receives a signal.
    if _owned(process):
        with suppress(ProcessLookupError):
            os.kill(process["pid"], signal.SIGTERM)
            deadline = time.monotonic() + 3
            while _owned(process) and time.monotonic() < deadline:
                time.sleep(0.05)
            if _owned(process):
                os.kill(process["pid"], signal.SIGKILL)


def _start(host: str, spec: str, *, reverse: bool, control: Path) -> dict:
    args = _ssh(host)
    args[-1:-1] = ["-o", "ClearAllForwardings=no", "-o", "ExitOnForwardFailure=yes",
                   "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=2",
                   "-o", "ControlMaster=yes", "-S", str(control), "-N", "-T", "-R" if reverse else "-L", spec]
    # -S overrides the inherited ControlPath=none. No shell or agent socket is forwarded.
    with tempfile.TemporaryFile() as errors:
        child = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=errors, start_new_session=True)
        deadline = time.monotonic() + 12
        try:
            while time.monotonic() < deadline:
                if child.poll() is not None:
                    errors.seek(0)
                    raise ProxmoxError(f"SSH forwarding failed: {errors.read().decode(errors='replace')[-600:]}")
                if control.exists():
                    check = subprocess.run(["ssh", "-S", str(control), "-O", "check", host],
                                           capture_output=True, timeout=2, check=False)
                    if check.returncode == 0:
                        proof = _process(child.pid)
                        if proof and proof["argv"] == args:
                            return proof
                time.sleep(0.05)
            raise ProxmoxError("SSH forwarding did not become ready within 12 seconds")
        except BaseException:
            # Until reaped, this exact Popen child cannot have its PID reused.
            if child.poll() is None:
                child.terminate()
            try:
                child.wait(timeout=3)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=3)
            raise


def forward(client, vmid: str, port: int, destination_vmid: str | None = None) -> dict:
    if not 1 <= port <= 65535:
        raise ProxmoxError("Service port must be between 1 and 65535")
    host, cfg = _guest(client, vmid, lab=True)
    destination = _guest(client, destination_vmid, lab=False) if destination_vmid else None
    identity = hashlib.sha256(f"{vmid}:{port}:{destination_vmid or ''}".encode()).hexdigest()[:24]
    with _locked() as root:
        path = root / f"{identity}.json"
        if path.exists():
            previous = json.loads(path.read_text())
            if previous.get("host") == host and previous.get("destination_host") == (destination[0] if destination else None) and all(_owned(p) for p in previous["processes"]):
                return {**previous, "reused": True}
            _close(root, identity)
        _verify(host, cfg)
        if destination:
            _verify(*destination)
        local_port = _free_port()
        result = {"id": identity, "vmid": vmid, "port": port, "host": host,
                  "local_url": f"http://127.0.0.1:{local_port}", "destination_vmid": destination_vmid,
                  "destination_host": destination[0] if destination else None,
                  "destination_url": None, "processes": [], "reused": False}
        try:
            result["processes"].append(_start(host, f"127.0.0.1:{local_port}:{host}:{port}", reverse=False, control=root / f"{identity}.s"))
            if destination:
                remote_port = _remote(destination[0], "python3 -c 'import socket; s=socket.socket(); s.bind((\"127.0.0.1\",0)); print(s.getsockname()[1])'")
                if not remote_port.isdecimal() or not 1 <= int(remote_port) <= 65535:
                    raise ProxmoxError("Destination did not return a valid loopback port")
                result["processes"].append(_start(destination[0], f"127.0.0.1:{remote_port}:127.0.0.1:{local_port}", reverse=True, control=root / f"{identity}.d"))
                result["destination_url"] = f"http://127.0.0.1:{remote_port}"
            path.write_text(json.dumps(result))
            path.chmod(0o600)
            return result
        except BaseException:
            for process in reversed(result["processes"]):
                _stop(process)
            raise


def _close(root: Path, identity: str) -> bool:
    path = root / f"{identity}.json"
    if not path.exists():
        return False
    record = json.loads(path.read_text())
    for process in reversed(record["processes"]):
        _stop(process)
    path.unlink()
    for suffix in ("s", "d"):
        with suppress(FileNotFoundError):
            (root / f"{identity}.{suffix}").unlink()
    return True


def close(identity: str) -> dict:
    if not re.fullmatch(r"[0-9a-f]{24}", identity):
        raise ProxmoxError("Use the transport id returned by st vm forward")
    with _locked() as root:
        return {"id": identity, "closed": _close(root, identity)}
