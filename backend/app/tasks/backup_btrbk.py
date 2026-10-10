"""Native Linux recovery using btrbk, driven by the existing backup workflow.

The root-owned btrbk configuration owns coverage and retention. Receipts describe
observed operations; they are not another scheduling or retention policy store.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import secrets
import shlex
import shutil
import stat
import subprocess
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from ..config import get_settings
from ..project_identity import get_project_aliases, get_project_identity
from ..storage import backups as backup_store
from ..storage.projects import list_projects, testing_project_ids
from ..utils import safe_subprocess
from ..utils.shared_paths import get_workspaces_root
from ._retention_policy import HostRetentionPolicy
from .backup_activity import BackupCancelled, run_bulk_process
from .backup_native_archive import PROJECT_DATABASE_PAYLOAD_NAME, _load_db_config
from .backup_utils import _FREQUENCY_DELTAS

REQUIRED_SOURCES = {"/", "/home", "/srv/workspaces", "/var/lib/docker", "/srv/models", "/var/log"}
CONFIG_PATH = Path("/etc/btrbk/summitflow.conf")
PACKAGE_STATUS_PATH = Path("/var/lib/dpkg/status")
ADAPTER = "summitflow-btrbk-v1"
SPACE_GUARD = "/usr/local/libexec/summitflow-btrfs-space-guard"
_RUN_ID = re.compile(r"\d{8}T\d{6}Z-[0-9a-f]{8}\Z")


def _state_root() -> Path:
    return Path.home() / ".local/state/summitflow/host-recovery"


def _enabled() -> bool:
    override = os.environ.get("BACKUP_BTRBK_ENABLED")
    if override is not None:
        return override.lower() in {"1", "true", "yes"}
    return get_settings().backup_btrbk_enabled


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return safe_subprocess.run(args, capture_output=True, text=True, check=False)


def _checked(args: list[str], *, bulk: bool = False) -> str:
    result = run_bulk_process(args, phase="host_recovery") if bulk else _run(args)
    if result.returncode:
        raise RuntimeError(f"{args[0]} failed (exit {result.returncode}); inspect host recovery journal")
    return result.stdout


def _rows(output: str) -> list[dict[str, str]]:
    return [dict(token.split("=", 1) for token in shlex.split(line) if "=" in token) for line in output.splitlines() if line.startswith("format=")]


def _configuration() -> list[dict[str, str]]:
    # btrbk executes shell commands. Never execute a caller-writable configuration
    # with sudo, including an imported configuration or a mutable symlink parent.
    path = CONFIG_PATH
    for item in [path, *path.parents]:
        info = item.lstat()
        if stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise RuntimeError("Native host configuration must have root-owned, non-writable parents")
    if "include" in path.read_text().split():
        raise RuntimeError("Included host configuration files require separate qualification")
    options = {line.strip() for line in path.read_text().splitlines() if line.strip() and not line.lstrip().startswith("#")}
    required = {"snapshot_preserve_min latest", "snapshot_preserve no", "target_preserve_min latest", "target_preserve 7d", "snapshot_create ondemand"}
    if not required.issubset(options):
        raise RuntimeError("Host configuration does not declare the approved bounded retention and capture policy")
    # Even `list config` takes btrbk's operational lock without --dry-run.
    # An unprivileged probe must not create a lock that blocks sudo captures.
    output = _checked(["btrbk", "-c", str(path), "--dry-run", "--format", "raw", "list", "config"])
    rows = _rows(output)
    sources = {row.get("source_url") for row in rows}
    if not REQUIRED_SOURCES.issubset(sources):
        raise RuntimeError("Native host coverage is missing required source subvolumes")
    if any(row.get("source_host") or row.get("target_host") or row.get("target_type") != "send-receive" for row in rows):
        raise RuntimeError("This host adapter requires qualified local Btrfs send-receive targets")
    targets = {row.get("target_path") for row in rows}
    if len(targets) != 1 or not next(iter(targets)):
        raise RuntimeError("Native host recovery requires one explicit destination")
    return rows


def _validate_nested_coverage(rows: list[dict[str, str]]) -> None:
    sources = {Path(row["source_url"]) for row in rows}
    snapshot_dirs = {Path(row["snapshot_path"]) for row in rows}
    for source in sources:
        fsroot = str(_filesystem(str(source)).get("fsroot", "/")).strip("/")
        prefix = fsroot + "/" if fsroot else ""
        output = _checked(["sudo", "-n", "btrfs", "subvolume", "list", "-o", str(source)])
        for line in output.splitlines():
            _, marker, path = line.partition(" path ")
            if not marker or not path.startswith(prefix):
                continue
            nested = source / path.removeprefix(prefix)
            if nested in sources or any(nested.is_relative_to(directory) for directory in snapshot_dirs):
                continue
            # Work recovery points are nested, disposable snapshot boundaries;
            # all other nested contents need an explicit host coverage section.
            if nested.is_relative_to(get_workspaces_root() / ".snapshots"):
                continue
            raise RuntimeError(f"Nested subvolume needs explicit host coverage: {nested}")


def _verified_points(rows: list[dict[str, str]], transactions: list[dict[str, str]]) -> list[dict[str, str]]:
    captured = {item["source_url"]: item["target_url"] for item in transactions if item.get("type") == "snapshot" and item.get("status") == "success"}
    received = {item["source_url"]: item["target_url"] for item in transactions if item.get("type") == "send-receive" and item.get("status") == "success"}
    points = []
    for row in rows:
        source = row["source_url"]
        snapshot = captured.get(source)
        target = received.get(snapshot or "")
        if not snapshot or not target or Path(target).parent != Path(row["target_path"]):
            raise RuntimeError(f"No current received point for required source: {source}")
        src = _checked(["sudo", "-n", "btrfs", "subvolume", "show", snapshot])
        dst = _checked(["sudo", "-n", "btrfs", "subvolume", "show", target])
        def identity(output: str, key: str) -> str:
            return next((line.split(":", 1)[1].strip() for line in output.splitlines() if line.strip().startswith(key + ":")), "")
        uuid = identity(src, "UUID")
        if not uuid or identity(dst, "Received UUID") != uuid:
            raise RuntimeError(f"Received identity mismatch for {source}")
        if _checked(["sudo", "-n", "btrfs", "property", "get", "-ts", target, "ro"]).strip() != "ro=true":
            raise RuntimeError(f"Received point is not read-only: {source}")
        points.append({"source": source, "snapshot": snapshot, "target": target, "source_uuid": uuid, "received_uuid": uuid})
    return points


def _filesystem(path: str) -> dict[str, Any]:
    raw = _checked(["findmnt", "--json", "-T", path, "-o", "TARGET,FSTYPE,UUID,OPTIONS,FSROOT,SOURCE"])
    requested = Path(os.path.realpath(path))
    mounts = json.loads(raw)["filesystems"]
    if not mounts or any(not Path(str(mount.get("target", ""))).is_absolute() or not requested.is_relative_to(Path(mount["target"])) for mount in mounts):
        raise RuntimeError(f"Cannot qualify the effective filesystem at {path}")
    # findmnt can report the systemd autofs layer before the real mount. Only
    # discard that layer at the deepest matching mountpoint; a Btrfs ancestor
    # must never hide a different filesystem mounted over the requested path.
    depth = max(len(Path(mount["target"]).parts) for mount in mounts)
    effective = [mount for mount in mounts if len(Path(mount["target"]).parts) == depth]
    real = [mount for mount in effective if mount.get("fstype") != "autofs"]
    if len(real or effective) != 1:
        raise RuntimeError(f"Ambiguous effective filesystem at {path}")
    return (real or effective)[0]


def _receipt() -> dict[str, Any] | None:
    path = _state_root() / "latest.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def _write_receipt(payload: dict[str, Any]) -> None:
    root = _state_root()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if root.is_symlink() or root.stat().st_uid != os.getuid() or root.stat().st_mode & 0o077:
        raise RuntimeError("Host receipt directory must be private and service-owned")
    if payload.get("adapter") == ADAPTER and _RUN_ID.fullmatch(str(payload.get("run_id", ""))):
        receipts = root / "receipts"
        receipts.mkdir(mode=0o700, exist_ok=True)
        _write_json(receipts / f"{payload['run_id']}.json", payload)
    _write_json(root / "latest.json", payload)
    if payload.get("status") == "completed":
        _write_json(root / "last-good.json", payload)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=".receipt-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(payload, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _qualify_target_directory(path: Path) -> None:
    if not path.is_absolute() or path == Path(path.anchor):
        raise RuntimeError("Native metadata needs a bounded absolute destination")
    for item in (path, *path.parents):
        owner, mode, kind = _checked(["sudo", "-n", "stat", "-c", "%u:%a:%F", "--", str(item)]).strip().split(":", 2)
        if owner != "0" or int(mode, 8) & 0o022 or kind != "directory":
            raise RuntimeError("Native target metadata must have root-owned, non-writable directory parents")


def _target_copy(source: Path, destination: Path) -> None:
    """Install and verify bytes before publishing the independent artifact."""
    _qualify_target_directory(destination.parent)
    temporary = destination.with_name(destination.name + ".preparing")
    _checked(["sudo", "-n", "install", "-m", "600", "--", str(source), str(temporary)])
    actual = _checked(["sudo", "-n", "sha256sum", "--", str(temporary)]).split()[0]
    if actual != hashlib.sha256(source.read_bytes()).hexdigest():
        raise RuntimeError("Independent host metadata checksum mismatch")
    _checked(["sudo", "-n", "mv", "-T", "--", str(temporary), str(destination)])
    _checked(["sudo", "-n", "sync", "-f", str(destination)])


def _database_manifests(rows: list[dict[str, str]], now: datetime) -> dict[str, Any]:
    """Associate configured project databases with fresh, qualified catalogue points.

    These are separate application recovery points, never an atomic claim about
    the online host filesystem. Credentials and raw database URLs are omitted.
    """
    sources = backup_store.list_sources()
    testing = testing_project_ids()
    projects = {str(item["id"]): item for item in list_projects()}
    for source in sources:
        if source.get("project_id"):
            projects.setdefault(str(source["project_id"]), {"id": source["project_id"], "root_path": source.get("path")})
    manifests, missing, excluded = [], [], []
    endpoints: dict[str, tuple[str, str, str]] = {}
    cadences: dict[str, timedelta] = {}
    seen_projects: set[str] = set()
    for project_id, project in projects.items():
        path = str(project.get("root_path") or "")
        if not path or not Path(path).is_absolute() or not any(Path(path).is_relative_to(Path(row["source_url"])) for row in rows):
            continue
        identity = get_project_identity(project_id, path) or {}
        canonical_id = str((identity.get("project") or {}).get("id") or project_id)
        if canonical_id in seen_projects:
            continue
        seen_projects.add(canonical_id)
        aliases = set(get_project_aliases(project_id, path)) | {project_id}
        registered = [source for source in sources if source.get("project_id") in aliases and source.get("source_type") == "project"]
        if registered and all(source.get("frequency") in _FREQUENCY_DELTAS for source in registered):
            cadences[canonical_id] = min(_FREQUENCY_DELTAS[source["frequency"]] for source in registered)
        try:
            config = _load_db_config(Path(path).name, {"BACKUP_PROJECT_ID": canonical_id})
        except RuntimeError:
            missing.append({"project_id": canonical_id, "reason": "database-configuration-unresolved", "source_ids": []})
            continue
        if config["configured"] != "true":
            continue
        if project_id in testing and registered and all(source.get("enabled") is False for source in registered):
            excluded.append({"project_id": canonical_id, "reason": "disabled-testing-portable-policy", "source_ids": [source["id"] for source in registered], "portable_database_recovery_covered": False, "protection": "Host filesystem points only; database state is crash-consistent, not a portable application recovery point"})
            continue
        host = {"localhost": "127.0.0.1", "::1": "127.0.0.1"}.get(config["host"], config["host"])
        endpoints[canonical_id] = (host, config["port"], config["name"])
        candidates: list[dict[str, Any]] = []
        # Qualified points that only miss the cadence window. They never satisfy
        # the obligation; they let the receipt say stale rather than absent.
        stale: list[tuple[str, timedelta]] = []
        for source in registered:
            offset = 0
            while True:
                page, total = backup_store.list_backups(source_id=str(source["id"]), limit=100, offset=offset)
                for item in page:
                    verification = item.get("verification_json") or {}
                    if item.get("source_id") != source["id"] or item.get("project_id") not in aliases:
                        continue
                    if item.get("status") not in {"completed", "completed_pending_upload"} or item.get("verified") is not True or verification.get("has_db") is not True or verification.get("verified") is not True or verification.get("structural_check_pending"):
                        continue
                    timestamp = verification.get("verified_at") or verification.get("structural_check_at") or item.get("verified_at")
                    captured_at = item.get("started_at") or item.get("created_at")
                    try:
                        verified_at = datetime.fromisoformat(str(timestamp))
                        captured = datetime.fromisoformat(str(captured_at))
                        window = _FREQUENCY_DELTAS[str(source["frequency"])]
                        if verified_at.tzinfo is None or captured.tzinfo is None or not captured <= verified_at <= now:
                            continue
                    except (ValueError, KeyError):
                        continue
                    offsite = verification.get("offsite") or {}
                    # A separate portable artifact must already exist independently.
                    if offsite.get("status") != "verified":
                        continue
                    if verification.get("format") == "restic-v1" and not all(verification.get(key) for key in ("repository_id", "snapshot_id", "remote_repository_id", "remote_snapshot_id")):
                        continue
                    if not item.get("location"):
                        continue
                    if now - captured > window:
                        stale.append((captured.astimezone(UTC).isoformat(), window))
                        continue
                    candidates.append({"project_id": canonical_id, "registered_project_id": project_id, "source_project_id": source["project_id"], "backup_project_id": item["project_id"], "source_id": source["id"], "backup_id": item["id"],
                                       "captured_at": captured.astimezone(UTC).isoformat(), "verified_at": verified_at.isoformat(),
                                       "has_db": True, "verified": True, "restore_verified": False,
                                       "location": item["location"], "storage_backend_id": item.get("storage_backend_id"),
                                       "checksum": item.get("checksum") or verification.get("checksum"),
                                       "offsite": {key: offsite[key] for key in ("status", "location", "provider_id", "remote_path", "provider_checksum", "verification_method") if key in offsite},
                                       "repository": {key: verification[key] for key in ("format", "repository_id", "snapshot_id", "remote_repository_id", "remote_snapshot_id") if key in verification},
                                       "db_dump_name": verification.get("capture", {}).get("db_dump_name")})
                offset += len(page)
                if not page or offset >= total:
                    break
        if candidates:
            manifests.append(max(candidates, key=lambda item: item["captured_at"]))
        elif stale:
            latest, window = max(stale)
            missing.append({"project_id": canonical_id, "reason": "verified-database-point-stale", "source_ids": [source["id"] for source in registered],
                            "latest_verified_captured_at": latest, "freshness_window_seconds": int(window.total_seconds())})
        else:
            missing.append({"project_id": canonical_id, "reason": "fresh-independent-verified-database-point-unavailable", "source_ids": [source["id"] for source in registered]})
    unresolved = []
    for obligation in missing:
        project_id = obligation["project_id"]
        shared = next((item for item in manifests if project_id in endpoints and project_id in cadences and endpoints.get(item["project_id"]) == endpoints[project_id]
                       and now - datetime.fromisoformat(item["captured_at"]) <= cadences[project_id]
                       and item["repository"].get("format") == "restic-v1" and Path(item.get("db_dump_name") or "").name == PROJECT_DATABASE_PAYLOAD_NAME), None)
        if shared is None:
            unresolved.append(obligation)
        else:
            manifests.append({**shared, "project_id": project_id, "registered_project_id": project_id, "database_point_project_id": shared["project_id"], "association_method": "verified-same-endpoint-full-database"})
    missing = unresolved
    # An empty registry is a broken catalogue view (for example a test
    # database), never evidence that no project needs database recovery.
    registry_empty = not projects
    if registry_empty:
        missing.append({"project_id": None, "reason": "project-registry-empty", "source_ids": []})
    return {"as_of": now.isoformat(), "status": "qualified" if not missing else "partial", "manifests": manifests, "missing": missing, "excluded": excluded,
            "consistency": "Separate portable database points; online host filesystems are not application-consistent"}


def _boot_layout() -> dict[str, Any]:
    """Record actual root/boot block-device ancestry, never a device-name guess."""
    mounts, disks = [], set()
    for path in ("/", "/boot", "/boot/efi"):
        if path != "/" and not Path(path).exists():
            continue
        mount = _filesystem(path)
        source = str(mount.get("source") or "").split("[", 1)[0]
        if not source.startswith("/dev/"):
            raise RuntimeError("Host boot layout requires qualified block-device mount sources")
        ancestry = _checked(["lsblk", "--inverse", "--raw", "--noheadings", "--paths", "--output", "NAME,TYPE", source])
        found = {parts[0] for line in ancestry.splitlines() if len(parts := line.split()) == 2 and parts[1] == "disk" and parts[0].startswith("/dev/")}
        if not found:
            raise RuntimeError("Host boot block-device ancestry cannot be qualified")
        disks.update(found)
        mounts.append({"path": path, "source": source, "uuid": mount.get("uuid"), "fsroot": mount.get("fsroot")})
    return {"mounts": mounts, "disks": [{"device": disk, "partition_layout": _checked(["sudo", "-n", "sfdisk", "--dump", disk])} for disk in sorted(disks)], "restore_verified": False}


def _publish_capture(payload: dict[str, Any], operation: Path) -> None:
    target_directory = Path(payload["boot_path"]).parent
    expected = Path(payload["target"]).parent / "summitflow-host-recovery" / "captures" / str(payload["run_id"])
    if not _RUN_ID.fullmatch(str(payload["run_id"])) or target_directory != expected or Path(payload["boot_path"]) != expected / "boot":
        raise RuntimeError("Native metadata path does not match its qualified capture identity")
    for name in ("journal.log", "layout.json", "database-manifests.json"):
        if payload.get("status") in {"completed", "partial"} and payload.get("capture_complete") and not (operation / name).is_file():
            raise RuntimeError("Retained host capture is missing a required metadata artifact")
        if (operation / name).is_file():
            _target_copy(operation / name, target_directory / name)
    candidate = operation / "publication.json"
    _write_json(candidate, payload)
    # The completion receipt is the final target artifact; local completion
    # becomes visible only after its verified, durable independent publication.
    _target_copy(candidate, target_directory / "capture.json")
    _write_receipt(payload)


def _cleanup_superseded(target: Path, current_run: str) -> dict[str, Any]:
    """Remove only successful adapter metadata whose referenced points are gone."""
    metadata = target.parent / "summitflow-host-recovery" / "captures"
    _qualify_target_directory(metadata)
    live = set(_checked(["sudo", "-n", "find", str(target), "-mindepth", "1", "-maxdepth", "1", "-type", "d", "-print"]).splitlines())
    captures = _checked(["sudo", "-n", "find", str(metadata), "-mindepth", "1", "-maxdepth", "1", "-type", "d", "-print"]).splitlines()
    removed, blockers = [], []
    before = shutil.disk_usage(target)
    for value in captures:
        directory = Path(value)
        if directory.parent != metadata or directory.name == current_run or not _RUN_ID.fullmatch(directory.name):
            continue
        try:
            _qualify_target_directory(directory)
            receipt = directory / "capture.json"
            owner, mode, kind = _checked(["sudo", "-n", "stat", "-c", "%u:%a:%F", "--", str(receipt)]).strip().split(":", 2)
            if owner != "0" or int(mode, 8) & 0o077 or kind != "regular file":
                raise RuntimeError("Unqualified native capture receipt")
            saved = json.loads(_checked(["sudo", "-n", "cat", "--", str(receipt)]))
            points = saved.get("points") or []
            if saved.get("adapter") != ADAPTER or saved.get("run_id") != directory.name or saved.get("status") != "completed" or saved.get("boot_path") != str(directory / "boot") or not points:
                continue
            if any(Path(point["target"]).parent != target or point["target"] in live for point in points):
                continue
            # The receipt remains until boot and its auxiliary artifacts delete
            # successfully. Failed deletion always keeps the local catalogue.
            _checked(["sudo", "-n", "rm", "-rf", "--", str(directory / "boot")])
            for name in ("journal.log", "layout.json", "database-manifests.json", "capture.json.preparing"):
                _checked(["sudo", "-n", "rm", "-f", "--", str(directory / name)])
            _checked(["sudo", "-n", "rm", "--", str(receipt)])
            _checked(["sudo", "-n", "rmdir", "--", str(directory)])
            last_good_path = _state_root() / "last-good.json"
            if last_good_path.is_file():
                last_good = json.loads(last_good_path.read_text())
                if last_good.get("run_id") == directory.name:
                    # Keep the historical completed catalogue without presenting
                    # already expired native points as available for recovery.
                    last_good["point_availability"] = "expired"
                    _write_json(last_good_path, last_good)
            local = _state_root() / "operations" / directory.name
            if local.exists():
                shutil.rmtree(local)
            (_state_root() / "receipts" / f"{directory.name}.json").unlink(missing_ok=True)
            removed.append(directory.name)
        except (OSError, ValueError, RuntimeError, KeyError) as exc:
            blockers.append({"run_id": directory.name, "error": str(exc)})
    _checked(["sudo", "-n", "sync", "-f", str(target)])
    after = shutil.disk_usage(target)
    return {"result": "partial" if blockers else "completed", "removed": removed, "blockers": blockers,
            "reclaimed_bytes": max(0, before.used - after.used), "free_bytes": after.free,
            "evidence": "Observed target usage before/after metadata cleanup; concurrent growth can mask reclamation"}


def _allocation_headroom(path: str, uuid: str) -> dict[str, Any]:
    """Read the existing guard's policy and physical allocation measurement."""
    try:
        result = _run(["sudo", "-n", SPACE_GUARD, "--check-only", "--path", path, "--uuid", uuid])
        report = json.loads(result.stdout)
        if not isinstance(report, dict) or result.returncode not in {0, 1} or result.stderr.strip() or report.get("path") != path or report.get("uuid") != uuid or report.get("error") or report.get("deferred"):
            raise ValueError("Unqualified Btrfs allocation report")
        usage, policy = report["after"], report["policy"]
        values = {name: usage[name] for name in ("size", "unallocated", "missing", "free", "metadata_size", "metadata_used")}
        values.update({name: policy[name] for name in ("trigger_bytes", "target_bytes")})
        if any(type(value) is not int or value < 0 for value in values.values()) or not 0 < values["metadata_size"] <= values["size"] or values["metadata_used"] > values["metadata_size"] or max(values["free"], values["unallocated"]) > values["size"] or not 0 < values["trigger_bytes"] <= values["target_bytes"]:
            raise ValueError("Invalid Btrfs allocation measurement")
        # Metadata sizes are logical even with DUP. Do not add its unused
        # bytes to physical unallocated space or change allocation profiles.
        return {"available": True, **values,
                "metadata_used_percent": values["metadata_used"] / values["metadata_size"] * 100,
                "admitted": values["missing"] == 0 and values["unallocated"] >= values["trigger_bytes"]}
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        return {"available": False, "admitted": False, "error": str(exc)}


def _capacity(rows: list[dict[str, str]], last: dict[str, Any] | None) -> dict[str, Any]:
    policy = HostRetentionPolicy.from_env()
    reserve = int(policy.pressure_min_free_gb * 1024**3)
    target = str(rows[0]["target_path"])
    target_fs = _filesystem(target)
    if target_fs["fstype"] != "btrfs" or not target_fs.get("uuid") or "compress=" not in target_fs.get("options", ""):
        raise RuntimeError("Native destination must be mounted Btrfs with compression enabled")
    if _filesystem(str(Path(target).parent)).get("uuid") != target_fs["uuid"]:
        raise RuntimeError("Native boot metadata parent must reside on the independent target filesystem")
    source_usage: dict[str, Any] = {}
    for source in sorted({row["source_url"] for row in rows}):
        fs = _filesystem(source)
        if fs["fstype"] != "btrfs" or not fs.get("uuid"):
            raise RuntimeError(f"Source is not a mounted Btrfs subvolume: {source}")
        if fs["uuid"] == target_fs.get("uuid"):
            raise RuntimeError("Host recovery destination must be independent of all source filesystems")
        if Path(source).stat().st_ino != 256:
            raise RuntimeError(f"Source is not an actual Btrfs subvolume root: {source}")
        if fs["uuid"] not in source_usage:
            usage = shutil.disk_usage(source)
            source_usage[fs["uuid"]] = {"path": source, "filesystem_uuid": fs["uuid"], "used_bytes": usage.used, "free_bytes": usage.free, "under_pressure": usage.used / usage.total * 100 >= policy.pressure_disk_percent,
                                       "allocation": _allocation_headroom(source, fs["uuid"])}
    # Initially budget the observed physical footprint of each distinct source
    # filesystem. Retain that conservative bound so a missing incremental parent
    # cannot silently turn a small admitted job into an oversized full capture.
    boot_bound, boot_filesystems = 0, set(source_usage)
    for path in ("/boot", "/boot/efi"):
        if path != "/boot" and not Path(path).exists():
            continue
        boot_fs = _filesystem(path)
        if not boot_fs.get("uuid") or boot_fs["uuid"] == target_fs["uuid"]:
            raise RuntimeError("Boot capture source must have a qualified independent mount identity")
        if boot_fs["uuid"] not in boot_filesystems:
            boot_bound += shutil.disk_usage(path).used
            boot_filesystems.add(boot_fs["uuid"])
    growth = max(sum(item["used_bytes"] for item in source_usage.values()) + boot_bound, int((last or {}).get("growth_peak_bytes", 0)))
    target_usage = shutil.disk_usage(target)
    target_allocation = _allocation_headroom(target, target_fs["uuid"])
    allocations = [item["allocation"] for item in source_usage.values()] + [target_allocation]
    reason = None
    if any(not item["available"] for item in allocations):
        reason = "btrfs-allocation-headroom-unavailable"
    elif any(item["missing"] for item in allocations):
        reason = "btrfs-device-missing"
    elif any(not item["admitted"] for item in allocations):
        reason = "insufficient-btrfs-allocation-headroom"
    elif target_usage.free - growth < reserve or any(item["free_bytes"] < reserve for item in source_usage.values()):
        reason = "insufficient-host-policy-headroom"
    return {"admitted": reason is None, "expected_growth_bytes": growth, "boot_growth_bound_bytes": boot_bound, "target_filesystem_uuid": target_fs["uuid"], "reserve_bytes": reserve, "free_bytes": target_usage.free, "used_bytes": target_usage.used, "target_allocation": target_allocation, "source_filesystems": list(source_usage.values()), "under_pressure": target_usage.used / target_usage.total * 100 >= policy.pressure_disk_percent, "reason": reason}


def native_host_status() -> dict[str, Any]:
    last_good = _state_root() / "last-good.json"
    result: dict[str, Any] = {"engine": "btrbk", "enabled": _enabled(), "installed": shutil.which("btrbk") is not None, "configured": CONFIG_PATH.is_file(), "ready": False, "restore_verified": False, "retention": "7 daily destination points; required source incremental parents", "windows_method": "Veeam", "last_result": _receipt(), "last_good_result": json.loads(last_good.read_text()) if last_good.is_file() else None}
    if not result["installed"]:
        result["blocked_reason"] = "btrbk is not installed"
        return result
    if not result["configured"]:
        result["blocked_reason"] = "Native destination and root-owned configuration await storage cutover"
        return result
    try:
        rows = _configuration()
        _validate_nested_coverage(rows)
        _qualify_target_directory(Path(rows[0]["target_path"]).parent)
        result.update(sources=sorted({row["source_url"] for row in rows}), target=rows[0]["target_path"], capacity=_capacity(rows, result["last_result"]))
        dry = _run(["sudo", "-n", "btrbk", "-c", str(CONFIG_PATH), "--dry-run", "--format", "raw", "run"])
        result["ready"] = dry.returncode == 0 and result["capacity"]["admitted"]
        result["blocked_reason"] = None if result["ready"] else result["capacity"]["reason"] or "btrbk coverage/destination preflight failed"
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        result["blocked_reason"] = str(exc)
    return result


def _check_received_points(points: list[dict[str, str]]) -> None:
    for point in points:
        output = _checked(["sudo", "-n", "btrfs", "subvolume", "show", point["target"]])
        received = next((line.split(":", 1)[1].strip() for line in output.splitlines() if line.strip().startswith("Received UUID:")), "")
        if received != point["source_uuid"] or _checked(["sudo", "-n", "btrfs", "property", "get", "-ts", point["target"], "ro"]).strip() != "ro=true":
            raise RuntimeError("Retained host point cannot be qualified for association retry")


def _finish_capture(payload: dict[str, Any], operation: Path, rows: list[dict[str, str]], now: datetime) -> dict[str, Any]:
    databases = _database_manifests(rows, now)
    _write_json(operation / "database-manifests.json", databases)
    final = dict(payload)
    reason = "database-recovery-incomplete" if databases["status"] != "qualified" else "metadata-cleanup-incomplete" if payload.get("metadata_cleanup", {}).get("blockers") else None
    final.update(database_recovery=databases, association_checked_at=now.isoformat(), artifacts_complete=True,
                 status="partial" if reason else "completed", reason=reason)
    final.pop("error", None)
    _publish_capture(final, operation)
    return final


def _resume_association(last: dict[str, Any], now: datetime) -> dict[str, Any]:
    """Finish retained native points without another boot copy or host capture."""
    root = _state_root()
    with (root / "run.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"status": "skipped", "reason": "host-backup-active"}
        rows = _configuration()
        if last.get("adapter") != ADAPTER or not _RUN_ID.fullmatch(str(last.get("run_id", ""))) or last.get("target") != rows[0]["target_path"]:
            return {"status": "blocked", "reason": "retained-host-capture-identity-unqualified"}
        payload = dict(last)
        operation = root / "operations" / last["run_id"]
        try:
            expected_boot = Path(rows[0]["target_path"]).parent / "summitflow-host-recovery" / "captures" / last["run_id"] / "boot"
            if Path(last["boot_path"]) != expected_boot:
                raise RuntimeError("Retained host metadata path does not match its capture identity")
            _qualify_target_directory(Path(last["boot_path"]).parent)
            if _filesystem(last["target"]).get("uuid") != last.get("target_filesystem_uuid"):
                raise RuntimeError("Native target filesystem identity changed")
            _check_received_points(last["points"])
            if any(_filesystem(row["source_url"]).get("uuid") == last["target_filesystem_uuid"] for row in rows):
                raise RuntimeError("Native target is no longer independent of source filesystems")
            payload["metadata_cleanup"] = _cleanup_superseded(Path(last["target"]), last["run_id"])
            return _finish_capture(payload, operation, rows, now)
        except Exception as exc:
            payload.update(status="cancelled" if isinstance(exc, BackupCancelled) else "failed", error=str(exc))
            _write_receipt(payload)
            return payload


def run_native_host_backup(*, dry_run: bool = False, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    status = native_host_status()
    if dry_run:
        return {"status": "preview", **status}
    if not _enabled():
        return {"status": "skipped", "reason": "host-backup-disabled"}
    if not status["ready"]:
        return {"status": "blocked", "reason": status.get("blocked_reason"), "capacity": status.get("capacity")}
    root = _state_root()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if root.is_symlink() or root.stat().st_uid != os.getuid() or root.stat().st_mode & 0o077:
        return {"status": "blocked", "reason": "host-state-directory-unqualified"}
    with (root / "run.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"status": "skipped", "reason": "host-backup-active"}
        # Repeat admission under the operation lock. No job has started yet.
        rows = _configuration()
        _validate_nested_coverage(rows)
        before = _capacity(rows, _receipt())
        if not before["admitted"]:
            return {"status": "blocked", "reason": before["reason"], "capacity": before}
        stamp = now.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(4)
        operation = root / "operations" / stamp
        operation.mkdir(mode=0o700, parents=True)
        journal = operation / "journal.log"
        target = Path(rows[0]["target_path"])
        boot = target.parent / "summitflow-host-recovery" / "captures" / stamp / "boot"
        payload: dict[str, Any] = {"adapter": ADAPTER, "run_id": stamp, "status": "running", "started_at": now.isoformat(), "evidence": str(journal), "target": str(target), "boot_path": str(boot), "capacity": before, "restore_verified": False, "database_consistency": "Online host filesystem points; application databases restore from separate qualified portable dumps"}
        _write_receipt(payload)
        journal.write_text("Native host operation started; no completed capture published\n")
        journal.chmod(0o600)
        try:
            package_digest = hashlib.sha256(PACKAGE_STATUS_PATH.read_bytes()).hexdigest()
            _qualify_target_directory(target.parent)
            _checked(["sudo", "-n", "mkdir", "-p", "-m", "700", str(boot)])
            _qualify_target_directory(boot)
            _checked(["sudo", "-n", "rsync", "-aHAX", "--numeric-ids", "/boot/", str(boot) + "/"], bulk=True)
            proc = run_bulk_process(["sudo", "-n", "btrbk", "-c", str(CONFIG_PATH), "--format", "raw", "run"], phase="host_recovery")
            journal.write_text(proc.stdout + "\n" + proc.stderr)
            journal.chmod(0o600)
            if proc.returncode:
                raise RuntimeError(f"btrbk returned {proc.returncode}; retained journal includes partial captures and deletion failures")
            if hashlib.sha256(PACKAGE_STATUS_PATH.read_bytes()).hexdigest() != package_digest:
                raise RuntimeError("Package state changed across boot/native capture; matching boot recovery is unverified")
            payload["transactions"] = _rows(proc.stdout)
            points = _verified_points(rows, _rows(proc.stdout))
            _write_json(operation / "layout.json", _boot_layout())
            _checked(["sudo", "-n", "btrfs", "subvolume", "sync", str(target)], bulk=True)
            after = shutil.disk_usage(target)
            growth = max(0, after.used - before["used_bytes"])
            if _filesystem(str(target))["uuid"] != before["target_filesystem_uuid"]:
                raise RuntimeError("Native destination mount identity changed during capture")
            payload.update(capture_complete=True, points=points, package_digest=package_digest, target_filesystem_uuid=before["target_filesystem_uuid"], finished_at=datetime.now(UTC).isoformat(), growth_bytes=growth, growth_peak_bytes=max(growth, int((status.get("last_result") or {}).get("growth_peak_bytes", 0))), reclaimed_bytes=max(0, before["used_bytes"] - after.used), remaining_capacity_bytes=after.free,
                           reclamation_evidence="Observed net filesystem change across btrbk run; capture growth can mask pruning")
            _write_receipt(payload)
            payload["metadata_cleanup"] = _cleanup_superseded(target, stamp)
            return _finish_capture(payload, operation, rows, datetime.now(UTC))
        except Exception as exc:
            payload["status"] = "cancelled" if isinstance(exc, BackupCancelled) else "failed"
            payload["error"] = str(exc)
            with journal.open("a") as stream:
                stream.write(f"\n{payload['status']}: {exc}\n")
            # A failure journal/receipt is useful on the independent target too.
            # A copy failure keeps every local artifact; never erase orphan sets.
            try:
                _publish_capture(payload, operation)
            except (OSError, ValueError, RuntimeError) as copy_exc:
                payload["target_evidence_error"] = str(copy_exc)
        _write_receipt(payload)
        return payload


def run_scheduled_host_backup(now: datetime) -> dict[str, Any]:
    if not _enabled():
        return {"status": "skipped", "reason": "host-backup-disabled"}
    settings = get_settings()
    local = now.astimezone(ZoneInfo(settings.backup_schedule_timezone))
    last = _receipt()
    if last and datetime.fromisoformat(last["started_at"]).astimezone(local.tzinfo).date() == local.date():
        if last.get("status") == "completed":
            return {"status": "skipped", "reason": "daily-host-backup-current", "evidence": last.get("evidence")}
        if last.get("capture_complete"):
            # Association/metadata retry does not start another boot or host job.
            return _resume_association(last, now)
        return {"status": "partial", "reason": "daily-host-backup-incomplete", "evidence": last.get("evidence"), "last_result": last}
    start, end = settings.backup_schedule_start_hour, settings.backup_schedule_end_hour
    if start is not None and end is not None:
        within = start <= local.hour < end if start < end else local.hour >= start or local.hour < end
        if not within:
            return {"status": "skipped", "reason": "outside-host-backup-window"}
    return run_native_host_backup(now=now)
