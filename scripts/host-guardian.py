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
import re
import shutil
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
    if percent >= 90 or free_gib <= 10:
        state.issue("critical", f"{label}_disk_critical", f"{label} disk is {percent}% used with {free_gib} GiB free")
    elif percent >= 80 or free_gib <= 25:
        state.issue("warning", f"{label}_disk_warning", f"{label} disk is {percent}% used with {free_gib} GiB free")


def check_filesystems(state: CheckState) -> None:
    root = disk_snapshot(Path("/"))
    state.details["root_disk"] = root
    evaluate_disk(state, root, label="root")

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

    if command_exists("btrfs"):
        proc = run(["btrfs", "device", "stats", "/"], timeout=30)
        stats: dict[str, int] = {}
        for line in proc.stdout.splitlines():
            match = re.search(r"\.([a-z_]+)\s+(\d+)$", line.strip())
            if match:
                stats[match.group(1)] = int(match.group(2))
        state.details["btrfs_device_stats"] = stats
        nonzero = {key: value for key, value in stats.items() if value}
        if proc.returncode != 0 or nonzero:
            state.issue("critical", "btrfs_device_errors", f"Btrfs device errors detected: {nonzero or proc.stderr.strip()}")


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
    if status in {"Failed", "Warning"}:
        state.issue("critical", "veeam_latest_failed", f"Latest Veeam session is {status}")
    elif status not in {"Running", "Pending"} and age > timedelta(hours=60):
        state.issue("critical", "veeam_stale", f"Latest Veeam backup is {age.total_seconds() / 3600:.1f} hours old")
    elif status not in {"Running", "Pending"} and age > timedelta(hours=36):
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
    return json.dumps(
        {
            "status": payload["status"],
            "issues": [(item["severity"], item["code"], item["message"]) for item in payload["issues"]],
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
    check_veeam(state)
    payload = build_payload(state, mode=args.mode)
    persist(payload)
    print(json.dumps(payload, sort_keys=True))
    lock.close()
    return 2 if state.status == "critical" else 0


if __name__ == "__main__":
    raise SystemExit(main())
