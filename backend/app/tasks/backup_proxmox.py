"""Proxmox guests, guest files and cluster configuration stream into the repository over ssh.

Source paths name what to capture:

- ``proxmox://<pve>/<qemu|lxc>/<vmid>``: the whole guest via ``vzdump --stdout``.
- ``proxmox://<pve>/config``: a read-only SQLite dump of the cluster database
  (every guest's configuration lives there).
- ``proxmox://<pve>/<qemu|lxc>/<vmid>/files?via=...&path=...&exclude=...``:
  only the named paths inside a guest, as a tar stream. ``via`` is ``pct``
  (container, read with ``pct exec``) or ``agent`` (VM, read through its QEMU
  guest agent). There is no ssh alias via: every read goes through the
  Proxmox host's dispatcher, never through an alias that may hold a root key.
- ``proxmox://<pve>/host/files?path=...``: paths on the Proxmox host itself,
  such as bind-mounted data whose container is stopped.

Output is piped straight into Restic: nothing is written to Proxmox storage or
local scratch, so a capture can never fill pve-root or the scratch volume (the
agent path stages one bounded, compressed copy in the guest's /tmp and always
removes it). Snapshot mode never stops a running guest. A stopped guest whose
disks cannot have changed is reported offline once a backup of it exists.

The Proxmox host is reached only with SummitFlow's own key, which root binds to a
fixed dispatcher (scripts/pve-backup): this side sends a verb and a source id,
never a command, and the far side builds the config dump (without priv/ and any
*.key file), vzdump and file tars from the sources root installed there.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from ..services.backup_keys import backup_key_directory
from ..storage import backups as backup_store

PATH_SCHEME = "proxmox://"
CONFIG_DATABASE = "/var/lib/pve-cluster/config.db"
THIN_POOL_FULL_PERCENT = 98.0  # Snapshot copy-on-write must not exhaust the guest thin pool.
CONFIG_ESTIMATED_BYTES = 64 * 1024**2
SSH_OPTIONS = ("-o", "BatchMode=yes", "-o", "ConnectTimeout=20", "-o", "ServerAliveInterval=30", "-o", "ServerAliveCountMax=6")
PVE_BACKUP_KEY = "pve-backup.ed25519"  # In the backup key directory; root binds it to scripts/pve-backup/summitflow-pve-backup.
_TARGET = re.compile(
    r"proxmox://(?P<host>[A-Za-z0-9._-]{1,64})/"
    r"(?:(?P<kind>qemu|lxc)/(?P<vmid>[1-9][0-9]{0,8})(?P<files>/files)?|(?P<config>config)|(?P<pvehost>host)/files)"
    r"(?:\?(?P<query>[^#]*))?"
)
_GUEST_PATH = re.compile(r"/(?:[A-Za-z0-9._@+-][A-Za-z0-9 ._@+-]*/?)+")
_EXCLUDE = re.compile(r"[A-Za-z0-9 ._*@+/-]{1,128}")
_VIA = re.compile(r"agent|pct|host")


class ProxmoxGuestOffline(RuntimeError):
    """The guest is powered off and already backed up; its disks cannot have changed."""


@dataclass(frozen=True)
class FileSelection:
    via: str
    paths: tuple[str, ...]
    excludes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProxmoxTarget:
    host: str
    kind: str  # qemu, lxc, config, or host
    vmid: int | None = None
    files: FileSelection | None = None

    @property
    def filename(self) -> str:
        if self.kind == "config":
            return "pve-cluster-config.sql"
        if self.files is not None:
            owner = "host" if self.kind == "host" else f"{self.kind}-{self.vmid}"
            return f"files-{owner}.tar{'.gz' if self.files.via == 'agent' else ''}"
        return f"vzdump-{self.kind}-{self.vmid}.{'vma' if self.kind == 'qemu' else 'tar'}"


def _selection(query: str | None, *, kind: str) -> FileSelection | None:
    values = parse_qs(query or "", keep_blank_values=False, strict_parsing=bool(query))
    if set(values) - {"via", "path", "exclude"}:
        return None
    via = (values.get("via") or ["host" if kind == "host" else ""])[-1]
    paths = tuple(values.get("path") or ())
    excludes = tuple(values.get("exclude") or ())
    if not _VIA.fullmatch(via) or not paths or (kind == "host") != (via == "host") or (via == "pct" and kind != "lxc") or (via == "agent" and kind != "qemu"):
        return None
    if any(not _GUEST_PATH.fullmatch(path) or ".." in path.split("/") for path in paths) or any(not _EXCLUDE.fullmatch(item) for item in excludes):
        return None
    return FileSelection(via, paths, excludes)


def parse_target(path: str | None) -> ProxmoxTarget | None:
    match = _TARGET.fullmatch(str(path or ""))
    if not match:
        return None
    if match["config"]:
        return None if match["query"] else ProxmoxTarget(match["host"], "config")
    if match["pvehost"]:
        selection = _selection(match["query"], kind="host")
        return ProxmoxTarget(match["host"], "host", None, selection) if selection else None
    if match["files"]:
        selection = _selection(match["query"], kind=match["kind"])
        return ProxmoxTarget(match["host"], match["kind"], int(match["vmid"]), selection) if selection else None
    return None if match["query"] else ProxmoxTarget(match["host"], match["kind"], int(match["vmid"]))


def is_proxmox_path(path: str | None) -> bool:
    return str(path or "").startswith(PATH_SCHEME)


def source_target_path(source_id: str) -> str | None:
    """The registered Proxmox path of a source, which never exists locally."""
    source = backup_store.get_source(source_id) or {}
    path = source.get("path")
    return str(path) if is_proxmox_path(path) else None


def path_digest(path: str) -> str:
    """What the dispatcher checks: a source whose path changed here is refused until root re-installs it."""
    return hashlib.sha256(path.encode()).hexdigest()


@cache
def _resolve_alias(host: str) -> tuple[str, str, str]:
    """The address, user and port the owner's ssh config gives this alias; its IdentityFile is never used."""
    result = subprocess.run(["ssh", "-G", host], capture_output=True, text=True, timeout=10, check=False)
    values = dict(line.split(" ", 1) for line in result.stdout.splitlines() if " " in line)
    if result.returncode or not values.get("hostname"):
        raise RuntimeError(f"Cannot resolve the Proxmox host alias {host}")
    return values["hostname"], values.get("user") or "root", values.get("port") or "22"


def pve_ssh(host: str) -> list[str]:
    """ssh to the Proxmox host with SummitFlow's own forced-command key, never the owner key or the keyring agent."""
    key = backup_key_directory() / PVE_BACKUP_KEY
    if not key.is_file():
        raise RuntimeError(f"SummitFlow's Proxmox backup key {key} is missing; root installs it with scripts/pve-backup/install.sh")
    address, user, port = _resolve_alias(host)
    return ["ssh", "-F", "/dev/null", "-i", str(key), "-o", "IdentitiesOnly=yes", "-o", "IdentityAgent=none", *SSH_OPTIONS,
            "-o", f"UserKnownHostsFile={Path.home() / '.ssh' / 'known_hosts'}", "-p", port, f"{user}@{address}"]


def _ssh(host: str, *args: str, timeout: int = 120) -> str:
    try:
        result = subprocess.run([*pve_ssh(host), *args], capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Proxmox host {host} did not answer within {timeout}s") from exc
    if result.returncode:
        detail = (result.stderr or "").strip().splitlines()[-1:] or [f"exit {result.returncode}"]
        raise RuntimeError(f"Proxmox host {host} query failed: {detail[0][:300]}")
    return result.stdout


def guest_state(target: ProxmoxTarget) -> dict[str, Any]:
    resources = json.loads(_ssh(target.host, "guests"))
    for item in resources if isinstance(resources, list) else []:
        if item.get("vmid") == target.vmid and item.get("type") == target.kind:
            if item.get("template"):
                raise RuntimeError(f"Proxmox {target.kind} {target.vmid} is a template")
            return {"status": str(item.get("status")), "node": item.get("node"), "name": item.get("name"), "maxdisk": int(item.get("maxdisk") or 0)}
    raise RuntimeError(f"Proxmox {target.kind} {target.vmid} does not exist on {target.host}")


def thin_pool_percent(host: str) -> float | None:
    try:
        return float(_ssh(host, "thinpool", timeout=60).strip())
    except (RuntimeError, ValueError):
        return None


def _has_completed_backup(source_id: str) -> bool:
    rows, _ = backup_store.list_backups(source_id=source_id, limit=50)
    return any(row.get("status") in {"completed", "completed_pending_upload"} for row in rows)


def plan_capture(source_id: str, path: str) -> dict[str, Any]:
    """Resolve the stream command for one source, or refuse before anything runs."""
    target = parse_target(path)
    if target is None:
        raise RuntimeError(f"Invalid Proxmox source path for {source_id}")
    if target.kind == "config":
        return {
            "target": target, "estimated_bytes": CONFIG_ESTIMATED_BYTES,
            "command": [*pve_ssh(target.host), "capture", source_id, path_digest(path)],
            "capture": {"kind": "proxmox-config", "host": target.host, "database": CONFIG_DATABASE, "excludes": ["priv/", "*.key"]},
        }
    if target.files is not None:
        return _plan_files(source_id, target, path)
    state = guest_state(target)
    if state["status"] != "running" and _has_completed_backup(source_id):
        raise ProxmoxGuestOffline(f"Proxmox {target.kind} {target.vmid} is {state['status']}; its last backup is current")
    if target.kind == "lxc" and state["status"] == "running":
        percent = thin_pool_percent(target.host)
        if percent is not None and percent >= THIN_POOL_FULL_PERCENT:
            raise RuntimeError(f"Capture blocked: insufficient host-policy headroom on the Proxmox thin pool ({percent:.1f}% full)")
    return {
        "target": target, "estimated_bytes": state["maxdisk"],
        # The dispatcher runs vzdump --stdout (nothing written to Proxmox storage) in snapshot mode, which never stops the guest.
        "command": [*pve_ssh(target.host), "capture", source_id, path_digest(path)],
        "capture": {"kind": f"proxmox-{target.kind}", "host": target.host, "vmid": target.vmid, "node": state["node"],
                    "name": state["name"], "guest_status": state["status"], "mode": "snapshot"},
    }


FILES_ESTIMATED_BYTES = 1024**3  # First-run reserve; later runs use measured growth.


def _plan_files(source_id: str, target: ProxmoxTarget, path: str) -> dict[str, Any]:
    selection = target.files
    assert selection is not None
    capture: dict[str, Any] = {"kind": "proxmox-files", "host": target.host, "via": selection.via, "paths": list(selection.paths),
                               "excludes": list(selection.excludes), "compressed": selection.via == "agent"}
    if target.kind != "host":
        state = guest_state(target)
        if state["status"] != "running":
            # Files can only be read from a running guest; a stopped one cannot change.
            raise ProxmoxGuestOffline(f"Proxmox {target.kind} {target.vmid} is {state['status']}; file capture resumes when it runs")
        capture.update(vmid=target.vmid, node=state["node"], name=state["name"])
    # The dispatcher tars on the host, through pct exec, or inside the VM through its QEMU agent.
    command = [*pve_ssh(target.host), "capture", source_id, path_digest(path)]
    return {"target": target, "estimated_bytes": FILES_ESTIMATED_BYTES, "command": command, "capture": capture}


def run_proxmox_backup(*, source_id: str, project_dir: str, env: dict[str, str], local_only: bool = False) -> dict[str, Any]:
    if env.get("BACKUP_ENGINE") != "restic":
        raise RuntimeError("Proxmox backups stream into the repository engine only")
    plan = plan_capture(source_id, project_dir)
    from .backup_repository_runtime import run_repository_stream

    return run_repository_stream(
        source_id=source_id, env=env, command=plan["command"], filename=plan["target"].filename,
        capture=plan["capture"], estimated_bytes=plan["estimated_bytes"], local_only=local_only,
    )


def dispatcher_entry(path: str) -> dict[str, Any] | None:
    """What the Proxmox dispatcher captures for one source path, or None when it is not a valid Proxmox path."""
    target = parse_target(path)
    if target is None:
        return None
    files = target.files and {"via": target.files.via, "paths": list(target.files.paths), "excludes": list(target.files.excludes)}
    return {"digest": path_digest(path), "kind": target.kind, "vmid": target.vmid, "files": files}


def dispatcher_sources(host: str) -> dict[str, dict[str, Any]]:
    """The registered sources root installs on one Proxmox host (scripts/pve-backup/install.sh)."""
    sources = {}
    for source in backup_store.list_sources():
        path = str(source.get("path") or "")
        target = parse_target(path)
        entry = dispatcher_entry(path) if source.get("enabled") and target and target.host == host else None
        if entry:
            sources[str(source["id"])] = entry
    return sources


_HEADERS = {
    "proxmox-qemu": lambda head: head[:4] == b"VMA\x00",
    "proxmox-lxc": lambda head: head[257:262] == b"ustar",
    "proxmox-config": lambda head: head.startswith((b"PRAGMA", b"BEGIN TRANSACTION")),
    "proxmox-files": lambda head: head[:2] == b"\x1f\x8b" or head[257:262] == b"ustar",
}


def restore_instructions(backup: dict[str, Any]) -> str:
    verification = backup.get("verification_json") or {}
    capture = verification.get("capture") or {}
    snapshot, path = verification.get("snapshot_id"), verification.get("payload_path")
    host = capture.get("host", "<proxmox-host>")
    if capture.get("kind") == "proxmox-config":
        return (f"restic dump {snapshot} {path} > config.sql, then rebuild a config.db with sqlite3 on {host} while pve-cluster is stopped; "
                "the dump has no priv/ or *.key files: PVE regenerates its keys and certificates; re-create API tokens, TFA "
                "and root's authorized_keys (priv/) from the console")
    if capture.get("kind") == "proxmox-files":
        unpack = "gunzip | tar -xf - -C <isolated-dir>" if capture.get("compressed") else "tar -xf - -C <isolated-dir>"
        return f"restic dump {snapshot} {path} | {unpack}, then copy the reviewed files back"
    tool = "qmrestore - <new-vmid>" if capture.get("kind") == "proxmox-qemu" else "pct restore <new-vmid> -"
    return f"restic dump {snapshot} {path} | ssh {host} {tool}"


def verify_stream_backup(backup: dict[str, Any]) -> dict[str, Any]:
    """Read back the stored stream's size and format header from the local repository."""
    from .backup_repository_runtime import _backup_environment
    from .backup_restic import ResticAdapter, ResticConfig

    verification = backup.get("verification_json") or {}
    capture = verification.get("capture") or {}
    snapshot, path = str(verification.get("snapshot_id") or ""), str(verification.get("payload_path") or "")
    check = _HEADERS.get(str(capture.get("kind")))
    if not snapshot or not path or check is None:
        raise RuntimeError("Backup is not a recorded Proxmox stream capture")
    adapter = ResticAdapter(ResticConfig.from_env(_backup_environment(backup)))
    listing = adapter._run(adapter._command("ls", snapshot, path), phase="verification")
    nodes = [json.loads(line) for line in listing.stdout.splitlines() if line.strip().startswith("{")]
    node = next((item for item in nodes if item.get("path") == path and item.get("type") == "file"), None)
    expected = int(capture.get("stream_bytes") or 0)
    if node is None or int(node.get("size") or -1) != expected:
        raise RuntimeError(f"Stored stream size differs from the captured {expected} bytes")
    proc = subprocess.Popen(adapter._command("dump", snapshot, path), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=adapter._env())
    try:
        assert proc.stdout is not None
        head = proc.stdout.read(4096)
    finally:
        proc.kill()
        proc.wait()
    if not check(head):
        raise RuntimeError("Stored stream does not start with the expected dump format header")
    return {"ok": True, "snapshot_id": snapshot, "path": path, "size_bytes": expected, "header": capture.get("kind")}


def restore_stream_isolated(backup: dict[str, Any], destination: Path, *, remote: bool = False) -> dict[str, Any]:
    """Restore a Proxmox stream capture as its original dump file and prove size and format."""
    from .backup_repository_runtime import _backup_environment
    from .backup_restic import ResticAdapter, ResticConfig

    verification = backup.get("verification_json") or {}
    capture = verification.get("capture") or {}
    check = _HEADERS.get(str(capture.get("kind")))
    snapshot = str(verification.get("remote_snapshot_id") if remote else verification.get("snapshot_id") or "")
    if not snapshot or check is None:
        raise RuntimeError("Backup is not a recorded Proxmox stream capture")
    adapter = ResticAdapter(ResticConfig.from_env(_backup_environment(backup)))
    restored = adapter.restore(snapshot, destination, remote=remote)
    payload = Path(str(restored.get("payload_file") or ""))
    if not payload.is_file():
        raise RuntimeError("Restore did not produce the captured stream file")
    expected = int(capture.get("stream_bytes") or 0)
    if payload.stat().st_size != expected:
        raise RuntimeError(f"Restored stream has {payload.stat().st_size} bytes, captured {expected}")
    with payload.open("rb") as stream:
        if not check(stream.read(4096)):
            raise RuntimeError("Restored stream does not start with the expected dump format header")
    return {"status": "completed", "snapshot_id": snapshot, "payload_file": str(payload), "size_bytes": expected,
            "format": capture.get("kind"), "next_step": restore_instructions(backup)}


# The coverage contract: what is unique on each important guest, and the source that
# protects it. Guest configuration for every VM and container lives in the cluster
# database. Neri guests such as VM 120 are disposable by owner
# policy and get no disk backups; VM 120's .conf and cloud-init snippets stay
# covered by pve-host-files.
REQUIRED_TARGETS: dict[str, str] = {
    "proxmox-gem/config": "proxmox://proxmox-gem/config",
    "proxmox-gem/qemu/100 browser profiles": "proxmox://proxmox-gem/qemu/100/files",
    "proxmox-gem/lxc/140 /vault data": "source:blackbox-vault-archive",
    "proxmox-gem/lxc/140 /vault/identity": "proxmox://proxmox-gem/host/files",
    "proxmox-gem/lxc/150 ominull": "source:ominull-production-state",
}
FRESHNESS_HOURS = 36  # Daily captures plus a missed tick and a slow offsite copy.
# A powered-off guest cannot change, so its last backup stays current while it is
# offline, but only up to this cap: past it the owner must look at the guest.
OFFLINE_FRESHNESS_DAYS = 30
FRESHNESS_RECEIPT = Path.home() / ".local/state/summitflow/backup-freshness/proxmox.json"


def _covering_source(matcher: str, sources: list[dict[str, Any]]) -> dict[str, Any] | None:
    for source in sources:
        if not source.get("enabled"):
            continue
        if matcher.startswith("source:") and source.get("id") == matcher.removeprefix("source:"):
            return source
        path = str(source.get("path") or "")
        if not matcher.startswith("source:") and (path == matcher or path.startswith((f"{matcher}/", f"{matcher}?"))):
            return source
    return None


def _aware(value: Any) -> datetime:
    when = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return when if when.tzinfo else when.replace(tzinfo=UTC)


def freshness_receipt(now: datetime | None = None) -> dict[str, Any]:
    """Whether every covered guest and the cluster config has an offsite-verified backup newer than the limit."""
    from .backup_alerts import source_offline_since
    from .backup_offsite_restore_test import restore_verified

    current = now or datetime.now(UTC)
    sources = backup_store.list_sources()
    targets: list[dict[str, Any]] = []
    for label, matcher in REQUIRED_TARGETS.items():
        source = _covering_source(matcher, sources)
        entry: dict[str, Any] = {"target": label, "source_id": source and source["id"]}
        if source is None:
            targets.append({**entry, "status": "missing", "fresh": False})
            continue
        rows, _ = backup_store.list_backups(source_id=str(source["id"]), limit=50)
        verified = next((row for row in rows if row.get("status") == "completed" and ((row.get("verification_json") or {}).get("offsite") or {}).get("status") == "verified"), None)
        if verified is None:
            targets.append({**entry, "status": "never-verified", "fresh": False})
            continue
        verification = verified.get("verification_json") or {}
        when = _aware(verified.get("completed_at") or verified.get("created_at"))
        offsite_at = verification["offsite"].get("verified_at")
        offsite_when = _aware(offsite_at) if offsite_at else when
        age = (current - when).total_seconds() / 3600
        offline = source_offline_since(str(source["id"]))
        status, reason = "fresh", None
        if age > FRESHNESS_HOURS:
            if offline and age <= OFFLINE_FRESHNESS_DAYS * 24:
                status = "offline-unchanged"
            elif offline:
                status, reason = "stale", f"guest offline and its last backup is older than the {OFFLINE_FRESHNESS_DAYS}-day offline cap"
            else:
                status = "stale"
        targets.append({**entry, "status": status, "fresh": status != "stale", **({"reason": reason} if reason else {}),
                        "backup_id": verified["id"], "snapshot_id": verification.get("snapshot_id"),
                        "captured_at": when.isoformat(), "verified_at": offsite_when.isoformat(), "age_hours": round(age, 1), "offsite": "verified",
                        "restore_test_ok": source.get("last_restore_test_ok"),
                        # A real restore (monthly test), as opposed to the weekly readback above.
                        "restore_drill_ok": source.get("last_drill_ok"),
                        "restore_verified": restore_verified(source, now=current),  # passed within 35 days
                        "restore_drill_at": _aware(source["last_drill_at"]).isoformat() if source.get("last_drill_at") else None})
    return {"schema_version": 1, "generated_at": current.isoformat(), "max_age_hours": FRESHNESS_HOURS, "offline_max_age_days": OFFLINE_FRESHNESS_DAYS,
            "ok": all(item["fresh"] for item in targets), "targets": targets}


def write_freshness_receipt(now: datetime | None = None) -> dict[str, Any]:
    receipt = freshness_receipt(now)
    FRESHNESS_RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    temporary = FRESHNESS_RECEIPT.with_suffix(".tmp")
    temporary.write_text(json.dumps(receipt, indent=1, default=str) + "\n")
    os.replace(temporary, FRESHNESS_RECEIPT)
    return receipt


if __name__ == "__main__":
    import sys

    if sys.argv[1:2] != ["dispatcher-sources"] or len(sys.argv) != 3:
        sys.exit("usage: python -m app.tasks.backup_proxmox dispatcher-sources <pve-host-alias>")
    print(json.dumps(dispatcher_sources(sys.argv[2]), indent=1, sort_keys=True))
