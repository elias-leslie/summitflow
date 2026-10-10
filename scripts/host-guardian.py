#!/usr/bin/python3
"""Independent host health guard and conservative maintenance.

This script intentionally uses only the Python standard library and native OS
commands.  The installed copy runs from /usr/local/libexec, so PostgreSQL,
Hatchet, SummitFlow, and the workspace checkout are not runtime dependencies.
"""

from __future__ import annotations

import argparse
import json
import os
import pwd
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

STATE_DIR = Path(os.environ.get("HOST_GUARDIAN_STATE_DIR", "/var/lib/summitflow-host-guardian"))
STATUS_PATH = STATE_DIR / "status.json"
EVENTS_PATH = STATE_DIR / "events.jsonl"
LOCK_PATH = Path("/run/lock/summitflow-host-guardian.lock")
BACKUP_PATH = Path(os.environ.get("HOST_GUARDIAN_BACKUP_PATH", "/media/kasadis/Backups"))
COMPOSE_DIR = Path(
    os.environ.get("HOST_GUARDIAN_COMPOSE_DIR", "/srv/workspaces/projects/summitflow/docker/compose")
)
COMPOSE_FILE = COMPOSE_DIR / "docker-compose.yml"
COMPOSE_ENV = COMPOSE_DIR / ".env"
OPERATOR_USER = os.environ.get("HOST_GUARDIAN_USER", "kasadis")
NATIVE_CONFIG = Path("/etc/btrbk/summitflow.conf")
NATIVE_TARGET_PATH = Path(os.environ.get("HOST_GUARDIAN_NATIVE_TARGET_PATH", "/mnt/summitflow-native"))
DEVICE_STATS_PATHS = ("/", "/srv/workspaces", str(NATIVE_TARGET_PATH))
SPACE_GUARD = "/usr/local/libexec/summitflow-btrfs-space-guard"
CORE_CONTAINERS = (
    "summitflow-stack-postgres-1",
    "summitflow-stack-redis-1",
    "summitflow-stack-docker-socket-proxy-1",
    "summitflow-stack-hatchet-1",
)


@dataclass
class CheckState:
    issues: list[dict[str, str]] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)
    actions: list[str] = field(default_factory=list)

    def issue(self, severity: str, code: str, message: str) -> None:
        self.issues.append({"severity": severity, "code": code, "message": message})

    @property
    def status(self) -> str:
        severities = {item["severity"] for item in self.issues}
        if "critical" in severities:
            return "critical"
        if "warning" in severities:
            return "warning"
        return "healthy"


def now_utc() -> datetime:
    return datetime.now(UTC)


def system_uptime_seconds() -> float:
    try:
        return float(Path("/proc/uptime").read_text(encoding="utf-8").split()[0])
    except (OSError, ValueError, IndexError):
        return 86400.0



def run(
    args: list[str],
    *,
    timeout: int = 60,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=check,
        encoding="utf-8",
        errors="replace",
    )


def command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def disk_snapshot(path: Path) -> dict[str, Any]:
    usage = shutil.disk_usage(path)
    percent = round(usage.used * 100 / usage.total, 1) if usage.total else 0.0
    return {
        "path": str(path),
        "total_bytes": usage.total,
        "used_bytes": usage.used,
        "free_bytes": usage.free,
        "free_gib": round(usage.free / 1024**3, 1),
        "percent_used": percent,
    }


def evaluate_disk(state: CheckState, snapshot: dict[str, Any], *, label: str) -> None:
    percent = float(snapshot["percent_used"])
    free_gib = float(snapshot["free_gib"])
    if (percent >= 92 and free_gib <= 10) or percent >= 95 or free_gib <= 5:
        state.issue("critical", f"{label}_disk_critical", f"{label} disk is {percent}% used with {free_gib} GiB free")
    elif (percent >= 85 and free_gib <= 30) or free_gib <= 15:
        state.issue("warning", f"{label}_disk_warning", f"{label} disk is {percent}% used with {free_gib} GiB free")


def check_filesystems(state: CheckState) -> None:
    root = disk_snapshot(Path("/"))
    state.details["root_disk"] = root
    evaluate_disk(state, root, label="root")
    try:
        workspace = disk_snapshot(Path("/srv/workspaces"))
        state.details["workspace_disk"] = workspace
        evaluate_disk(state, workspace, label="workspace")
    except OSError as exc:
        state.issue("critical", "workspace_disk_unavailable", f"Workspace disk unavailable: {exc}")
    check_allocation_headroom(state)

    try:
        # The path is an automount; statvfs triggers the mount without coupling
        # this guard to Veeam or SummitFlow.
        backup = disk_snapshot(BACKUP_PATH)
    except OSError as exc:
        state.issue("critical", "backup_disk_unavailable", f"Backup disk unavailable: {exc}")
        state.details["backup_disk"] = {"path": str(BACKUP_PATH), "available": False}
    else:
        backup["available"] = True
        state.details["backup_disk"] = backup
        evaluate_disk(state, backup, label="backup")

    if NATIVE_CONFIG.exists():
        check_native_target_disk(state)

    if command_exists("btrfs"):
        check_device_stats(state)


def check_native_target_disk(state: CheckState) -> None:
    # The native btrbk target is an automount on the portable drive; statvfs
    # triggers the mount, and the same thresholds as the other disks apply.
    try:
        target = disk_snapshot(NATIVE_TARGET_PATH)
    except OSError as exc:
        state.issue("warning", "native_target_disk_unavailable", f"Native backup target unavailable: {exc}")
        state.details["native_target_disk"] = {"path": str(NATIVE_TARGET_PATH), "available": False}
        return
    target["available"] = True
    state.details["native_target_disk"] = target
    evaluate_disk(state, target, label="native_target")


def check_device_stats(state: CheckState) -> None:
    all_stats: dict[str, dict[str, int]] = {}
    native = state.details.get("native_target_disk")
    for path in DEVICE_STATS_PATHS:
        if path == str(NATIVE_TARGET_PATH) and not (isinstance(native, dict) and native.get("available")):
            # The portable native target is optional; its absence is already
            # reported by the disk check and is not a device error.
            continue
        proc = run(["btrfs", "device", "stats", path], timeout=30)
        stats: dict[str, int] = {}
        for line in proc.stdout.splitlines():
            match = re.search(r"\.([a-z_]+)\s+(\d+)$", line.strip())
            if match:
                stats[match.group(1)] = stats.get(match.group(1), 0) + int(match.group(2))
        all_stats[path] = stats
        nonzero = {key: value for key, value in stats.items() if value}
        if proc.returncode != 0 or not stats or nonzero:
            state.issue("critical", "btrfs_device_errors", f"Btrfs device errors detected on {path}: {nonzero or proc.stderr.strip() or 'no device stats'}")
    totals: dict[str, int] = {}
    for stats in all_stats.values():
        for key, value in stats.items():
            totals[key] = totals.get(key, 0) + value
    # Flat totals keep the existing consumer contract; per-path detail is additive.
    state.details["btrfs_device_stats"] = totals
    state.details["btrfs_device_stats_by_path"] = all_stats


def check_allocation_headroom(state: CheckState) -> None:
    try:
        proc = run([SPACE_GUARD, "--check-only"], timeout=300)
        reports = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
        if proc.returncode not in {0, 1} or proc.stderr.strip() or len(reports) != 2 or {report["path"] for report in reports} != {"/", "/srv/workspaces"}:
            raise ValueError("No qualified allocation reports for root and workspaces")
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as exc:
        state.details["btrfs_allocation"] = {"available": False}
        state.issue("warning", "btrfs_allocation_unavailable", f"Btrfs allocation measurement unavailable: {exc}")
        return
    state.details["btrfs_allocation"] = reports
    for report in reports:
        label = "root" if report["path"] == "/" else "workspace"
        try:
            if report.get("error") or report.get("deferred") or not report.get("uuid"):
                raise ValueError(report.get("error") or report.get("deferred") or "missing filesystem identity")
            usage, policy = report["after"], report["policy"]
            measured = [usage[name] for name in ("size", "free", "unallocated", "missing", "metadata_size", "metadata_used")]
            measured += [policy[name] for name in ("trigger_bytes", "target_bytes")]
            if any(type(value) is not int or value < 0 for value in measured) or not 0 < usage["metadata_size"] <= usage["size"] or usage["metadata_used"] > usage["metadata_size"] or max(usage["free"], usage["unallocated"]) > usage["size"] or not 0 < policy["trigger_bytes"] <= policy["target_bytes"]:
                raise ValueError("invalid allocation measurement")
        except (ValueError, KeyError, TypeError) as exc:
            state.issue("warning", f"{label}_allocation_unavailable", f"{label} allocation measurement unavailable: {exc}")
            continue
        report["metadata_used_percent"] = round(usage["metadata_used"] / usage["metadata_size"] * 100, 2)
        message = f"{label} has {usage['unallocated'] / 1024**3:.2f} GiB unallocated and {usage['free'] / 1024**3:.2f} GiB free"
        if usage["missing"] or usage["unallocated"] < policy["trigger_bytes"]:
            state.issue("critical", f"{label}_allocation_critical", message)
        elif usage["unallocated"] < policy["target_bytes"] or usage["free"] < 25 * 1024**3 or report.get("warning"):
            state.issue("warning", f"{label}_allocation_warning", message)


def systemctl_active(unit: str) -> bool:
    return run(["systemctl", "is-active", "--quiet", unit], timeout=20).returncode == 0


def compose_command(*args: str) -> list[str]:
    command = ["docker", "compose"]
    if COMPOSE_ENV.is_file():
        command.extend(["--env-file", str(COMPOSE_ENV)])
    command.extend(["-f", str(COMPOSE_FILE), *args])
    return command


def reconcile_infrastructure(state: CheckState) -> bool:
    if not COMPOSE_FILE.is_file():
        state.issue("critical", "compose_file_missing", f"Infrastructure Compose file missing: {COMPOSE_FILE}")
        return False
    proc = run(compose_command("--profile", "infra", "up", "-d", "--remove-orphans"), timeout=600)
    if proc.returncode != 0:
        state.issue("critical", "compose_reconcile_failed", (proc.stderr or proc.stdout).strip()[-500:])
        return False
    state.actions.append("reconciled SummitFlow infrastructure with Docker Compose")
    return True


def inspect_container(name: str) -> tuple[str, str]:
    proc = run(
        [
            "docker",
            "inspect",
            "--format",
            "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}",
            name,
        ],
        timeout=30,
    )
    if proc.returncode != 0:
        return "missing", "missing"
    status, _, health = proc.stdout.strip().partition("|")
    return status or "unknown", health or "none"


def check_infrastructure(state: CheckState, *, remediate: bool) -> None:
    if not systemctl_active("docker.service") and remediate:
        run(["systemctl", "restart", "docker.service"], timeout=120)
        state.actions.append("restarted Docker service")
    if not systemctl_active("docker.service"):
        state.issue("critical", "docker_inactive", "Docker service is inactive")
        return

    before = {name: inspect_container(name) for name in CORE_CONTAINERS}
    unhealthy = [name for name, (status, health) in before.items() if status != "running" or health not in {"healthy", "none"}]
    if unhealthy and remediate and reconcile_infrastructure(state):
        for _ in range(12):
            time.sleep(5)
            current = {name: inspect_container(name) for name in CORE_CONTAINERS}
            if all(status == "running" and health in {"healthy", "none"} for status, health in current.values()):
                break

    containers = {name: {"status": status, "health": health} for name, (status, health) in ((name, inspect_container(name)) for name in CORE_CONTAINERS)}
    state.details["core_containers"] = containers
    for name, detail in containers.items():
        if detail["status"] != "running" or detail["health"] not in {"healthy", "none"}:
            state.issue("critical", "core_container_unhealthy", f"{name} is {detail['status']}/{detail['health']}")

    if containers.get("summitflow-stack-postgres-1", {}).get("status") == "running":
        pg = run(["docker", "exec", "summitflow-stack-postgres-1", "pg_isready", "-U", "admin"], timeout=30)
        state.details["postgres_ready"] = pg.returncode == 0
        if pg.returncode != 0:
            state.issue("critical", "postgres_not_ready", (pg.stderr or pg.stdout).strip())


def check_smart(state: CheckState) -> None:
    if not command_exists("smartctl"):
        state.issue("warning", "smartctl_missing", "smartmontools is not installed")
        return
    scan = run(["smartctl", "--scan-open"], timeout=30)
    devices = []
    for line in scan.stdout.splitlines():
        parts = line.split()
        if parts and parts[0].startswith("/dev/"):
            devices.append(parts[0])
    results: dict[str, Any] = {}
    for device in devices:
        proc = run(["smartctl", "-H", "-A", device], timeout=60)
        text = f"{proc.stdout}\n{proc.stderr}"
        failed = bool(re.search(r"SMART overall-health.*FAILED|SMART Health Status:\s*BAD|Critical Warning:\s*0x0*[1-9a-f]", text, re.I))
        results[device] = {"ok": not failed, "returncode": proc.returncode}
        if failed:
            state.issue("critical", "smart_health_failed", f"SMART health failure reported for {device}")
    state.details["smart"] = results


def _read_native_receipt(path: Path, uid: int) -> dict[str, Any]:
    operator_gid = pwd.getpwuid(uid).pw_gid
    for parent in path.parents:
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid not in {0, uid} or info.st_mode & 0o002 or (info.st_mode & 0o020 and (info.st_uid != uid or info.st_gid != operator_gid)):
            raise ValueError("Unsafe native receipt directory")
        if parent == path.parent and (info.st_uid != uid or info.st_mode & 0o077):
            raise ValueError("Native receipt directory must be private and service-owned")
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), encoding="utf-8") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != uid or info.st_mode & 0o077:
            raise ValueError("Native receipt must be private and service-owned")
        receipt = json.load(handle)
    if not isinstance(receipt, dict) or receipt.get("adapter") != "summitflow-btrbk-v1" or not re.fullmatch(r"\d{8}T\d{6}Z-[0-9a-f]{8}", str(receipt.get("run_id", ""))):
        raise ValueError("Unqualified native receipt identity")
    if receipt.get("status") not in ("completed", "partial", "failed", "cancelled", "running", "blocked") or not isinstance(receipt.get("database_recovery", {}), dict) or receipt.get("point_availability") not in (None, "expired"):
        raise ValueError("Invalid native receipt status or database coverage")
    return receipt


def check_native_backup(state: CheckState) -> None:
    state.details["linux_backup_engine"] = "btrbk"
    try:
        for path in (NATIVE_CONFIG, *NATIVE_CONFIG.parents):
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
                raise ValueError("Native configuration must have root-owned, non-writable parents")
        if not stat.S_ISREG(NATIVE_CONFIG.lstat().st_mode):
            raise ValueError("Native configuration must be a regular file")
        operator = pwd.getpwnam(OPERATOR_USER)
        root = Path(operator.pw_dir) / ".local/state/summitflow/host-recovery"
        latest = _read_native_receipt(root / "latest.json", operator.pw_uid)
        good = _read_native_receipt(root / "last-good.json", operator.pw_uid)
    except (OSError, ValueError, KeyError) as exc:
        state.issue("warning", "native_backup_unavailable", f"Native backup receipt unavailable: {exc}")
        return
    reason = latest.get("reason")
    safe_reason = reason if isinstance(reason, str) and re.fullmatch(r"[a-z0-9-]{1,100}", reason) else None
    databases = latest.get("database_recovery") or {}
    state.details["native_backup"] = {"latest_status": latest.get("status"), "latest_reason": safe_reason,
                                      "last_good_run_id": good["run_id"], "point_availability": good.get("point_availability"),
                                      "restore_verified": False}
    latest_status = latest.get("status")
    if latest_status in {"failed", "cancelled", "blocked"}:
        state.issue("critical", "native_backup_failed", f"Latest native backup is {latest_status}")
    elif latest_status == "partial" or safe_reason:
        state.issue("warning", "native_backup_partial", f"Latest native backup is incomplete: {safe_reason or 'partial capture'}")
    elif latest_status not in {"completed", "running"}:
        state.issue("warning", "native_backup_status_unknown", "Latest native backup status is unqualified")
    if not isinstance(databases, dict) or databases.get("status") != "qualified" or databases.get("missing"):
        state.issue("warning", "native_database_recovery_incomplete", "Latest native capture lacks qualified application database recovery coverage")
    if good.get("point_availability") == "expired" or good.get("status") != "completed" or good.get("capture_complete") is not True or good.get("artifacts_complete") is not True or not isinstance(good.get("points"), list) or not good["points"]:
        state.issue("critical", "native_backup_points_unavailable", "Last completed native recovery points are expired or unqualified")
    elif good.get("database_recovery", {}).get("status") != "qualified" or good.get("database_recovery", {}).get("missing"):
        state.issue("warning", "native_database_recovery_incomplete", "Last completed native capture lacks qualified application database recovery coverage")
    try:
        captured = datetime.fromisoformat(str(good.get("finished_at") or good.get("started_at")))
        if captured.tzinfo is None or captured > now_utc():
            raise ValueError("unqualified capture timestamp")
        age = now_utc() - captured
        state.details["native_backup"]["last_good_captured_at"] = captured.isoformat()
        if age > timedelta(hours=60):
            state.issue("critical", "native_backup_stale", f"Last completed native backup is {age.total_seconds() / 3600:.1f} hours old")
        elif age > timedelta(hours=36):
            state.issue("warning", "native_backup_stale", f"Last completed native backup is {age.total_seconds() / 3600:.1f} hours old")
    except (ValueError, TypeError):
        state.issue("warning", "native_backup_timestamp_unqualified", "Native capture time cannot be qualified")


def check_backup(state: CheckState) -> None:
    if NATIVE_CONFIG.exists() or NATIVE_CONFIG.is_symlink():
        check_native_backup(state)
    else:
        state.details["linux_backup_engine"] = "veeam"
        check_veeam(state)


def check_veeam(state: CheckState) -> None:
    if not command_exists("veeamconfig"):
        state.issue("warning", "veeam_missing", "Veeam Agent is not installed")
        return
    if not systemctl_active("veeamservice.service"):
        run(["systemctl", "restart", "veeamservice.service"], timeout=120)
    if not systemctl_active("veeamservice.service"):
        state.issue("critical", "veeam_service_inactive", "Veeam service is inactive")
        return
    proc = run(["veeamconfig", "session", "list"], timeout=60)
    rows = [line for line in proc.stdout.splitlines() if re.search(r"\b(Backup|Restore)\b", line)]
    if not rows:
        state.issue("warning", "veeam_no_sessions", "No Veeam backup sessions were found")
        return
    latest = rows[-1]
    match = re.search(r"\b(Running|Pending|Success|Failed|Warning)\b.*?(\d{4}-\d{2}-\d{2} \d{2}:\d{2})", latest)
    state.details["veeam_latest"] = latest.strip()
    if not match:
        state.issue("warning", "veeam_status_unparsed", "Could not parse latest Veeam session")
        return
    status, timestamp = match.groups()
    created = datetime.strptime(timestamp, "%Y-%m-%d %H:%M").replace(tzinfo=datetime.now().astimezone().tzinfo).astimezone(UTC)
    age = now_utc() - created
    uptime = system_uptime_seconds()
    if status in {"Failed", "Warning"}:
        state.issue("critical", "veeam_latest_failed", f"Latest Veeam session is {status}")
    elif status not in {"Running", "Pending"} and age > timedelta(hours=60):
        if uptime < 7200:
            state.issue("info", "veeam_stale_boot_pending", f"Latest Veeam backup is {age.total_seconds() / 3600:.1f} hours old (boot catch-up pending)")
        else:
            state.issue("critical", "veeam_stale", f"Latest Veeam backup is {age.total_seconds() / 3600:.1f} hours old")
    elif status not in {"Running", "Pending"} and age > timedelta(hours=36):
        if uptime < 7200:
            state.issue("info", "veeam_stale_boot_pending", f"Latest Veeam backup is {age.total_seconds() / 3600:.1f} hours old (boot catch-up pending)")
        else:
            state.issue("warning", "veeam_stale", f"Latest Veeam backup is {age.total_seconds() / 3600:.1f} hours old")


def directory_size(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for root, _, files in os.walk(path):
        for name in files:
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                continue
    return total


def prune_anonymous_volumes(state: CheckState, *, min_age_hours: int = 48) -> None:
    proc = run(["docker", "volume", "ls", "-q", "-f", "dangling=true"], timeout=60)
    if proc.returncode != 0:
        return
    cutoff = now_utc() - timedelta(hours=min_age_hours)
    removed = 0
    for name in proc.stdout.splitlines():
        if not re.fullmatch(r"[0-9a-f]{64}", name.strip()):
            continue
        inspect = run(["docker", "volume", "inspect", name.strip()], timeout=30)
        try:
            created_raw = json.loads(inspect.stdout)[0]["CreatedAt"]
            created = datetime.fromisoformat(created_raw.replace("Z", "+00:00")).astimezone(UTC)
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError):
            continue
        if created > cutoff:
            continue
        if run(["docker", "volume", "rm", name.strip()], timeout=120).returncode == 0:
            removed += 1
    if removed:
        state.actions.append(f"removed {removed} anonymous Docker volume(s) older than {min_age_hours}h")


def run_user_command(args: list[str], *, timeout: int = 600) -> None:
    if not command_exists(args[0]):
        return
    run(["runuser", "-u", OPERATOR_USER, "--", *args], timeout=timeout)


def maintenance(state: CheckState) -> None:
    if systemctl_active("docker.service"):
        prune_anonymous_volumes(state)
        run(["docker", "container", "prune", "-f", "--filter", "until=168h"], timeout=300)
        run(["docker", "image", "prune", "-af", "--filter", "until=168h"], timeout=600)
        run(["docker", "builder", "prune", "-af", "--keep-storage", "2gb"], timeout=600)
        state.actions.append("pruned aged Docker containers/images and capped build cache at 2 GiB")

    run(["journalctl", "--vacuum-size=500M"], timeout=300)
    run(["apt-get", "clean"], timeout=300)
    state.actions.append("vacuumed journal/package caches")

    if command_exists("snap"):
        snaps = run(["snap", "list", "--all"], timeout=60)
        removed = 0
        for line in snaps.stdout.splitlines()[1:]:
            fields = line.split()
            if len(fields) >= 6 and fields[-1] == "disabled":
                if run(["snap", "remove", fields[0], f"--revision={fields[2]}"], timeout=300).returncode == 0:
                    removed += 1
        if removed:
            state.actions.append(f"removed {removed} disabled Snap revision(s)")

    run_user_command(["uv", "cache", "prune"])
    run_user_command(["go", "clean", "-cache"])

    spotify_cache = Path(f"/home/{OPERATOR_USER}/snap/spotify/common/.cache")
    spotify_running = run(["pgrep", "-u", OPERATOR_USER, "-f", "(^|/)spotify( |$)"], timeout=15).returncode == 0
    if not spotify_running and directory_size(spotify_cache) > 4 * 1024**3:
        for child in spotify_cache.iterdir():
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)
        state.actions.append("cleared inactive Spotify cache above 4 GiB")

    guestfs = Path("/var/tmp/.guestfs-0")
    if guestfs.exists() and now_utc().timestamp() - guestfs.stat().st_mtime > 7 * 86400:
        if run(["pgrep", "-f", "guestfs|libguestfs|qemu.*appliance"], timeout=15).returncode != 0:
            shutil.rmtree(guestfs, ignore_errors=True)
            state.actions.append("removed stale libguestfs appliance cache")


def build_payload(state: CheckState, *, mode: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "checked_at": now_utc().isoformat(),
        "mode": mode,
        "status": state.status,
        "requires_intervention": state.status != "healthy",
        "issues": state.issues,
        "actions": state.actions,
        "details": state.details,
    }


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        temp_name = handle.name
    os.chmod(temp_name, 0o644)
    os.replace(temp_name, path)


def event_fingerprint(payload: dict[str, Any]) -> str:
    issues = payload.get("issues") or []
    issue_tuples = sorted([(item["severity"], item["code"]) for item in issues if isinstance(item, dict) and "severity" in item and "code" in item])
    return json.dumps(
        {
            "status": payload.get("status", "healthy"),
            "issues": issue_tuples,
        },
        sort_keys=True,
    )


def persist(payload: dict[str, Any]) -> None:
    previous: dict[str, Any] | None = None
    try:
        previous = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    atomic_write_json(STATUS_PATH, payload)
    if previous is None or event_fingerprint(previous) != event_fingerprint(payload):
        event = {
            "event_id": f"{int(now_utc().timestamp())}-{os.getpid()}",
            "occurred_at": payload["checked_at"],
            "previous_status": previous.get("status") if previous else None,
            "status": payload["status"],
            "issues": payload["issues"],
            "actions": payload["actions"],
        }
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        with EVENTS_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True) + "\n")
        os.chmod(EVENTS_PATH, 0o644)


def acquire_lock() -> Any:
    import fcntl

    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    handle = LOCK_PATH.open("w", encoding="utf-8")
    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    return handle


def main() -> int:
    parser = argparse.ArgumentParser(description="Independent SummitFlow host guardian")
    parser.add_argument("mode", choices=("check", "maintain"), nargs="?", default="check")
    parser.add_argument("--no-remediate", action="store_true", help="Observe only; do not reconcile services")
    args = parser.parse_args()
    try:
        lock = acquire_lock()
    except BlockingIOError:
        print("host guardian already running", file=sys.stderr)
        return 0

    state = CheckState()
    if args.mode == "maintain":
        maintenance(state)
    check_filesystems(state)
    check_infrastructure(state, remediate=not args.no_remediate)
    check_smart(state)
    check_backup(state)
    payload = build_payload(state, mode=args.mode)
    persist(payload)
    print(json.dumps(payload, sort_keys=True))
    lock.close()
    return 2 if state.status == "critical" else 0


if __name__ == "__main__":
    raise SystemExit(main())
