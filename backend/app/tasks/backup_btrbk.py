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
from ..logging_config import get_logger
from ..project_identity import get_project_aliases, get_project_identity
from ..storage import backups as backup_store
from ..storage.projects import list_projects, testing_project_ids
from ..utils import safe_subprocess
from ..utils.maintenance_window import MaintenanceWindow
from ..utils.shared_paths import get_workspaces_root
from ._retention_policy import HostRetentionPolicy
from .backup_activity import BackupCancelled, run_bulk_process
from .backup_native_archive import PROJECT_DATABASE_PAYLOAD_NAME, _load_db_config
from .backup_offsite_restore_test import restore_verified
from .backup_utils import _FREQUENCY_DELTAS
from .backup_write_window import path_window

logger = get_logger(__name__)

REQUIRED_SOURCES = {"/", "/home", "/srv/workspaces", "/var/lib/docker", "/srv/models", "/var/log"}
CONFIG_PATH = Path("/etc/btrbk/summitflow.conf")
PACKAGE_STATUS_PATH = Path("/var/lib/dpkg/status")
ADAPTER = "summitflow-btrbk-v1"
# Backup admission needs this much unallocated Btrfs space per filesystem;
# host-level reclamation toward the target is Nightshift's job.
ALLOCATION_TRIGGER_BYTES = 8 * 1024**3
ALLOCATION_TARGET_BYTES = 12 * 1024**3
_USAGE_FIELDS = (("Device size", "size"), ("Device unallocated", "unallocated"), ("Device missing", "missing"), ("Free (statfs, df)", "free"))
_RUN_ID = re.compile(r"\d{8}T\d{6}Z-[0-9a-f]{8}\Z")
_BATCH_JITTER = timedelta(minutes=30)
NATIVE_HELPER = "/usr/local/sbin/summitflow-native-capture"
NATIVE_TARGET = Path("/mnt/summitflow-native/native")
SYSFS_BTRFS = Path("/sys/fs/btrfs")
# Listing subvolumes needs root's tree search; Nightshift's read-only diag
# route runs it, so admission never wraps a read in sudo.
_SUBVOLUME_ROW = re.compile(r"(\d+)\t(\d+)\t(\d+)\t+(\S.*)")


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


def _native(*args: str, bulk: bool = False) -> str:
    """Root file operations on the native store go through one fixed, path-confined helper."""
    return _checked(["sudo", "-n", NATIVE_HELPER, *args], bulk=bulk)


def _native_listing(target: Path, which: str) -> list[str]:
    if target != NATIVE_TARGET:
        raise RuntimeError("Native target differs from the root helper's fixed store")
    return _native("list", which).splitlines()


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
        for path in _child_subvolumes(source):
            nested = source / path
            if nested in sources or any(nested.is_relative_to(directory) for directory in snapshot_dirs):
                continue
            # Work recovery points are nested, disposable snapshot boundaries;
            # all other nested contents need an explicit host coverage section.
            # The default workspaces root is a symlink to the Btrfs mount; compare
            # resolved paths or every work snapshot looks like uncovered data.
            if nested.resolve().is_relative_to(get_workspaces_root().resolve() / ".snapshots"):
                continue
            raise RuntimeError(f"Nested subvolume needs explicit host coverage: {nested}")


def _child_subvolumes(source: Path) -> list[str]:
    """Direct child subvolumes of a mounted source, relative to it (`subvolume list -o`).

    The table lists every subvolume of the filesystem; a child of the listed
    mount's own subvolume is printed relative to that mount. Anything unreadable
    fails closed: a partial listing would hide uncovered nested data.
    """
    match = re.search(r"(?:^|,)subvolid=(\d+)(?:,|$)", str(_filesystem(str(source)).get("options", "")))
    if not match:
        raise RuntimeError(f"Cannot identify the subvolume mounted at {source}")
    result = _run(["nightshift", "request", "diag.read", "probe=btrfs.subvolumes", f"target={source}",
                   "--reason", "maintain", "--agent", "summitflow-host-backup", "--wait", "120"])
    try:
        response = json.loads(result.stdout) if result.returncode == 0 else {}
        listing = response.get("result") or {}
        output = str(listing.get("out", ""))
    except (ValueError, AttributeError):
        response, listing, output = {}, {}, ""
    lines = output.splitlines()
    if (response.get("outcome") != "applied" or listing.get("rc") != 0 or output.endswith("[truncated]")
            or len(lines) < 2 or lines[0].split() != ["ID", "gen", "top", "level", "path"] or not lines[1].startswith("--")):
        raise RuntimeError(f"Subvolume listing for {source} is unavailable or incomplete; inspect Nightshift diag.read")
    children = []
    for line in lines[2:]:
        row = _SUBVOLUME_ROW.fullmatch(line.rstrip("\t"))
        if not row:
            raise RuntimeError(f"Unexpected subvolume listing row for {source}")
        path = row.group(4)
        if row.group(3) != match.group(1):
            continue
        if path.startswith("/") or ".." in Path(path).parts:
            raise RuntimeError(f"Unexpected subvolume path below {source}")
        children.append(path)
    return children


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
    # The helper re-hashes the installed bytes and renames them into place only on a match.
    _native("publish", destination.parent.name, destination.name, str(source), hashlib.sha256(source.read_bytes()).hexdigest())


def _database_manifests(rows: list[dict[str, str]], now: datetime, reference: datetime | None = None) -> dict[str, Any]:
    """Associate configured project databases with fresh, qualified catalogue points.

    These are separate application recovery points, never an atomic claim about
    the online host filesystem. Credentials and raw database URLs are omitted.
    Freshness is judged against ``reference`` (the host capture time; ``now`` by
    default), so a later association retry never ages good points out.
    """
    reference = min(reference or now, now)
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
        # Testing projects without an enabled source, and projects whose owner
        # disabled every backup source, have no portable database obligation.
        # They are recorded, never silently dropped. A non-testing project with
        # no source at all stays an uncovered obligation.
        all_disabled = all(source.get("enabled") is False for source in registered)
        if all_disabled and (project_id in testing or canonical_id in testing or registered):
            reason = "disabled-testing-portable-policy" if (project_id in testing or canonical_id in testing) else "backup-source-disabled"
            excluded.append({"project_id": canonical_id, "reason": reason, "source_ids": [source["id"] for source in registered], "portable_database_recovery_covered": False, "protection": "Host filesystem points only; database state is crash-consistent, not a portable application recovery point"})
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
                        # A point taken by the previous scheduled batch can be a few minutes past
                        # its cadence when the capture starts; that is on schedule, not stale.
                        window = _FREQUENCY_DELTAS[str(source["frequency"])] + _BATCH_JITTER
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
                    if reference - captured > window:
                        stale.append((captured.astimezone(UTC).isoformat(), window))
                        continue
                    candidates.append({"project_id": canonical_id, "registered_project_id": project_id, "source_project_id": source["project_id"], "backup_project_id": item["project_id"], "source_id": source["id"], "backup_id": item["id"],
                                       "captured_at": captured.astimezone(UTC).isoformat(), "verified_at": verified_at.isoformat(),
                                       "has_db": True, "verified": True, "restore_verified": restore_verified(source, now=now),
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
                       and reference - datetime.fromisoformat(item["captured_at"]) <= cadences[project_id]
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


def _receipt_metadata(directory: Path) -> str | None:
    """Return the receipt's ``uid:mode:type``, or None when the receipt is absent.

    One root stat covers the directory and its receipt: the directory line
    proves the probe itself ran, and only stat's own not-found error for the
    receipt counts as absence; any other receipt error (I/O, permissions) stays
    a blocker rather than being reported as an uncatalogued directory.
    """
    receipt = directory / "capture.json"
    result = _run(["sudo", "-n", "stat", "-c", "%n|%u:%a:%F", "--", str(directory), str(receipt)])
    lines = dict(line.rsplit("|", 1) for line in result.stdout.splitlines() if "|" in line)
    absent = any(str(receipt) in line and line.endswith("No such file or directory") for line in result.stderr.splitlines())
    if str(directory) not in lines or (str(receipt) not in lines and not absent):
        raise RuntimeError(f"stat failed (exit {result.returncode}); inspect host recovery journal")
    return lines.get(str(receipt))


def _cleanup_superseded(target: Path, current_run: str) -> dict[str, Any]:
    """Remove only successful adapter metadata whose referenced points are gone."""
    metadata = target.parent / "summitflow-host-recovery" / "captures"
    _qualify_target_directory(metadata)
    live = set(_native_listing(target, "target"))
    captures = _native_listing(target, "captures")
    removed: list[str] = []
    blockers: list[dict[str, str]] = []
    uncatalogued: list[str] = []
    before = shutil.disk_usage(target)
    for value in captures:
        directory = Path(value)
        if directory.parent != metadata or directory.name == current_run or not _RUN_ID.fullmatch(directory.name):
            continue
        try:
            _qualify_target_directory(directory)
            metadata_line = _receipt_metadata(directory)
            if metadata_line is None:
                # An interrupted removal (or a directory holding only operator
                # files) has no receipt: it catalogues no recovery point, so it
                # is reported, never retried as a blocker or deleted blindly.
                uncatalogued.append(directory.name)
                continue
            owner, mode, kind = metadata_line.split(":", 2)
            if owner != "0" or int(mode, 8) & 0o077 or kind != "regular file":
                raise RuntimeError("Unqualified native capture receipt")
            saved = json.loads(_native("read", directory.name))
            points = saved.get("points") or []
            if saved.get("adapter") != ADAPTER or saved.get("run_id") != directory.name or saved.get("status") != "completed" or saved.get("boot_path") != str(directory / "boot") or not points:
                continue
            if any(Path(point["target"]).parent != target or point["target"] in live for point in points):
                continue
            # The receipt remains until boot and its auxiliary artifacts delete
            # successfully. Failed deletion always keeps the local catalogue.
            _native("remove", directory.name)
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
    _native("sync", "target")
    after = shutil.disk_usage(target)
    return {"result": "partial" if blockers else "completed", "removed": removed, "blockers": blockers, "uncatalogued": uncatalogued,
            "reclaimed_bytes": max(0, before.used - after.used), "free_bytes": after.free,
            "evidence": "Observed target usage before/after metadata cleanup; concurrent growth can mask reclamation"}


def _readable(path: str) -> bool:
    return os.access(path, os.R_OK | os.X_OK)


def _missing_devices(uuid: str) -> int:
    states = sorted((SYSFS_BTRFS / uuid / "devinfo").glob("*/missing"))
    if not states:
        raise ValueError("Btrfs device state is unavailable")
    return sum(int(state.read_text().strip()) for state in states)


def _allocation_headroom(path: str) -> dict[str, Any]:
    """Measure physical Btrfs allocation without root; works on read-only mounts.

    Unprivileged `filesystem usage` reports the overall figures from the space
    ioctls and only omits per-device chunk detail. It needs a readable directory
    on the filesystem: fall back from a root-only path to any mount of it.
    """
    try:
        fs = _filesystem(path)
        mounts = [line.split(" ", 1)[1] for line in _checked(["findmnt", "-rn", "-t", "btrfs", "-o", "UUID,TARGET"]).splitlines()
                  if line.startswith(f"{fs['uuid']} ")] if fs.get("uuid") else []
        measured = next((item for item in (path, fs.get("target"), *mounts) if item and _readable(str(item))), None)
        if measured is None:
            raise RuntimeError(f"No readable directory measures the filesystem at {path}")
        output = _checked(["btrfs", "filesystem", "usage", "-b", str(measured)])
        values: dict[str, int] = {}
        for label, name in _USAGE_FIELDS:
            match = re.search(r"^\s*" + re.escape(label) + r":\s*(\d+)\s*$", output, re.M)
            if not match:
                raise ValueError(f"Unexpected btrfs usage output for {label}")
            values[name] = int(match.group(1))
        metadata = re.findall(r"^Metadata,[^:]+: Size:(\d+), Used:(\d+)", output, re.M)
        if not metadata:
            raise ValueError("Missing Btrfs metadata usage")
        values["metadata_size"] = sum(int(size) for size, _ in metadata)
        values["metadata_used"] = sum(int(used) for _, used in metadata)
        values["missing_devices"] = _missing_devices(str(fs["uuid"]))
        if not 0 < values["metadata_size"] <= values["size"] or values["metadata_used"] > values["metadata_size"] or max(values["free"], values["unallocated"]) > values["size"]:
            raise ValueError("Invalid Btrfs allocation measurement")
        # Metadata sizes are logical even with DUP. Do not add its unused
        # bytes to physical unallocated space or change allocation profiles.
        return {"available": True, **values, "trigger_bytes": ALLOCATION_TRIGGER_BYTES, "target_bytes": ALLOCATION_TARGET_BYTES,
                "metadata_used_percent": values["metadata_used"] / values["metadata_size"] * 100,
                "admitted": values["missing"] == 0 and not values["missing_devices"] and values["unallocated"] >= ALLOCATION_TRIGGER_BYTES}
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
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
                                       "allocation": _allocation_headroom(source)}
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
    target_allocation = _allocation_headroom(target)
    allocations = [item["allocation"] for item in source_usage.values()] + [target_allocation]
    reason = None
    if any(not item["available"] for item in allocations):
        reason = "btrfs-allocation-headroom-unavailable"
    elif any(item["missing"] or item.get("missing_devices") for item in allocations):
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
    try:
        reference: datetime | None = datetime.fromisoformat(str(payload.get("finished_at")))
    except ValueError:
        reference = None
    databases = _database_manifests(rows, now, reference if reference and reference.tzinfo else None)
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
            with path_window(rows[0]["target_path"]):
                return _resume_retained(last, payload, operation, rows, now)
        except Exception as exc:
            payload.update(status="cancelled" if isinstance(exc, BackupCancelled) else "failed", error=str(exc))
            _write_receipt(payload)
            return payload


def _resume_retained(last: dict[str, Any], payload: dict[str, Any], operation: Path, rows: list[dict[str, str]], now: datetime) -> dict[str, Any]:
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


def _target_deletions_refused(target: Path) -> bool:
    """Preview btrbk expiry; refuse (preserve backups) when it exceeds daily retention."""
    try:
        return _target_deletions_exceed_retention(target)
    except Exception as exc:
        # Unknown plan: keep every point this run; the real run still reports errors.
        logger.warning("btrbk_deletion_preview_failed", target=str(target), error=str(exc))
        return True


def _target_deletions_exceed_retention(target: Path) -> bool:
    from .backup_safety import guard_deletion

    plan = _run(["sudo", "-n", "btrbk", "-c", str(CONFIG_PATH), "--dry-run", "--format", "raw", "run"])
    if plan.returncode:
        return False  # The real run reports the failure.
    deleting = [Path(row.get("target_url", "")).name for row in _rows(plan.stdout)
                if row.get("type", "").startswith("delete") and Path(row.get("target_url", "")).parent == target]
    existing = [Path(path).name for path in _native_listing(target, "target")]
    groups: dict[str, tuple[int, int]] = {}
    for name in existing:
        removed, total = groups.get(name.split(".", 1)[0], (0, 0))
        groups[name.split(".", 1)[0]] = (removed + (name in deleting), total + 1)
    # Seven daily points per subvolume: normal expiry removes one or two.
    return not guard_deletion("btrbk-target", str(target), delete=len(deleting), total=len(existing), groups=groups,
                              total_fraction=0.34, total_min=6, group_fraction=0.34, group_min=2)


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
        window = path_window(target)
        window.__enter__()
        try:
            package_digest = hashlib.sha256(PACKAGE_STATUS_PATH.read_bytes()).hexdigest()
            _qualify_target_directory(target.parent)
            if target != NATIVE_TARGET:
                raise RuntimeError("Native target differs from the root helper's fixed store")
            _native("copy-boot", stamp, bulk=True)
            _qualify_target_directory(boot)
            preserve = _target_deletions_refused(target)
            payload["target_deletions_refused"] = preserve
            proc = run_bulk_process(["sudo", "-n", "btrbk", "-c", str(CONFIG_PATH), *(["--preserve-backups"] if preserve else []), "--format", "raw", "run"], phase="host_recovery")
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
        finally:
            window.__exit__(None, None, None)
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
    if settings.backup_schedule_window and not MaintenanceWindow.parse(settings.backup_schedule_window).contains(
        now, ZoneInfo(settings.backup_schedule_timezone),
    ):
        return {"status": "skipped", "reason": "outside-host-backup-window"}
    return run_native_host_backup(now=now)
