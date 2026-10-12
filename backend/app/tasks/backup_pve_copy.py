"""Copy local restic snapshots to the append-only repository on davion-gem.

The target (scripts/pve-restic-append) accepts appends through one SSH key
whose forced command runs an append-only restic server inside CT 160, so this
side can add snapshots but never delete them; retention runs on PVE. The copy
is enabled by ``pve-copy.json`` in the restic key directory, for example::

    {"host": "192.168.86.39", "key": "pve-append.ed25519", "max_age_hours": 26}

Each run records a ``pve_copy`` section in the backup safety status, which
also carries the PVE-side maintenance status read through the same key.
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from ..logging_config import get_logger
from .backup_activity import run_bulk_process
from .backup_restic import ResticConfig, repository_lock
from .backup_safety import read_status, record_section

logger = get_logger(__name__)

CONFIG_NAME = "pve-copy.json"
REPOSITORY = "rclone:pve-append:repo"  # The path is ignored by the forced command.
COPY_INTERVAL = timedelta(hours=3)
PVE_MAINTENANCE_MAX_AGE = timedelta(days=9)  # Weekly timer plus slack.


def _settings(config: ResticConfig) -> dict[str, Any] | None:
    path = config.key_directory / CONFIG_NAME
    try:
        settings = json.loads(path.read_text())
    except FileNotFoundError:
        return None
    if not isinstance(settings, dict) or not settings.get("host") or not settings.get("key"):
        raise ValueError(f"{path} needs host and key")
    return settings


def _ssh_args(config: ResticConfig, settings: Mapping[str, Any]) -> list[str]:
    key = config.key_directory / str(settings["key"])
    known_hosts = Path(str(settings.get("known_hosts") or Path.home() / ".ssh" / "known_hosts"))
    return ["-F", "/dev/null", "-i", str(key), "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
            "-o", f"UserKnownHostsFile={known_hosts}", "-o", "ServerAliveInterval=30",
            f"{settings.get('user', 'root')}@{settings['host']}"]


def restic_command(config: ResticConfig, settings: Mapping[str, Any], *args: str) -> list[str]:
    """restic against the PVE copy; the local password also opens it (one secret to keep)."""
    return ["nice", "-n", "15", "ionice", "-c", "3", "restic", "--repo", REPOSITORY,
            "--password-file", str(config.local_password_file), "--no-cache",
            "-o", "rclone.program=ssh", "-o", "rclone.args=" + " ".join(_ssh_args(config, settings)), *args]


def _env() -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if not key.startswith(("RESTIC_", "RCLONE_"))}
    env["LC_ALL"] = "C"
    return env


def _remote_status(config: ResticConfig, settings: Mapping[str, Any]) -> dict[str, Any]:
    try:
        result = subprocess.run(["ssh", *_ssh_args(config, settings), "status"], capture_output=True, text=True, timeout=60, check=False)
        value = json.loads(result.stdout) if result.returncode == 0 else {}
        return value if isinstance(value, dict) else {}
    except (subprocess.SubprocessError, OSError, ValueError):
        return {}


def _parse(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def assess(section: Mapping[str, Any], remote: Mapping[str, Any], *, now: datetime, max_age_hours: float) -> list[dict[str, str]]:
    """Alerts for a stale copy or unhealthy PVE-side maintenance."""
    alerts = []
    last = _parse(section.get("last_success_at"))
    if last is None or now - last > timedelta(hours=max_age_hours):
        age = f"{(now - last).total_seconds() / 3600:.0f}h ago" if last else "never"
        alerts.append({"kind": "stale", "message": f"The PVE backup copy last succeeded {age} (limit {max_age_hours:.0f}h). Last error: {section.get('error') or 'none recorded'}"})
    finished = _parse(remote.get("finished_at"))
    if remote and finished and now - finished > PVE_MAINTENANCE_MAX_AGE:
        alerts.append({"kind": "pve-maintenance-stale", "message": f"PVE copy maintenance last ran {finished.date().isoformat()}"})
    for alert in remote.get("alerts") or []:
        alerts.append({"kind": f"pve-{alert.get('kind', 'alert')}", "message": f"PVE copy: {alert.get('message', '')}"})
    return alerts


def default_restic_env() -> dict[str, str] | None:
    """Environment of the default restic backend, whose local repository is copied."""
    from ..storage import backups as backup_store
    from .backup_utils import storage_config_env

    backends = [backend for backend in backup_store.list_backends(enabled_only=True)
                if isinstance(backend.get("config"), Mapping) and backend["config"].get("engine") == "restic"]
    backends.sort(key=lambda backend: not backend.get("is_default"))
    if not backends:
        return None
    backend = backends[0]
    return storage_config_env({**backend["config"], "__backend_type": backend["backend_type"], "__backend_id": backend["id"]})


def run_scheduled_copy_and_health(*, window_open: bool) -> dict[str, Any]:
    """Scheduler hook: copy every tick (rate-limited), weekly health inside the backup window."""
    env = default_restic_env()
    if env is None:
        return {"status": "skipped", "reason": "no-restic-backend"}
    result: dict[str, Any] = {}
    try:
        result["pve_copy"] = sync_pve_copy(env)
    except Exception as exc:
        logger.exception("pve_copy_unhandled")
        result["pve_copy"] = {"status": "error", "error": str(exc)[:300]}
    from .backup_weekly_health import refresh_check_status, run_weekly_health

    try:
        result["restic_checks"] = refresh_check_status(env)
    except Exception as exc:
        logger.exception("restic_check_status_unhandled")
        result["restic_checks"] = {"status": "error", "error": str(exc)[:300]}
    if window_open:
        try:
            result["weekly_health"] = run_weekly_health(env)
        except Exception as exc:
            logger.exception("weekly_health_unhandled")
            result["weekly_health"] = {"status": "error", "error": str(exc)[:300]}
    return result


def sync_pve_copy(env: Mapping[str, str], *, force: bool = False, now: datetime | None = None) -> dict[str, Any]:
    """Copy new local snapshots; skip when the last success is recent."""
    current = now or datetime.now(UTC)
    config = ResticConfig.from_env(dict(env))
    settings = _settings(config)
    if settings is None:
        return {"status": "skipped", "reason": "pve-copy-not-configured"}
    max_age = float(settings.get("max_age_hours", 26))
    previous = (read_status().get("sections") or {}).get("pve_copy") or {}
    last = _parse(previous.get("last_success_at"))
    section: dict[str, Any] = {key: previous.get(key) for key in ("last_success_at", "last_attempt_at") if previous.get(key)}
    if not force and last and current - last < COPY_INTERVAL:
        result: dict[str, Any] = {"status": "skipped", "reason": "recent-copy"}
    else:
        section["last_attempt_at"] = current.isoformat()
        try:
            with repository_lock(config):
                proc = run_bulk_process(
                    restic_command(config, settings, "copy", "--from-repo", str(config.local_repository),
                                   "--from-password-file", str(config.local_password_file)),
                    env=_env(), phase="pve_copy", object_name="PVE append-only copy")
            if proc.returncode:
                raise RuntimeError(f"restic copy to PVE failed (exit {proc.returncode})")
            section["last_success_at"] = datetime.now(UTC).isoformat()
            result = {"status": "verified"}
        except Exception as exc:
            logger.warning("pve_copy_failed", error=str(exc))
            section["error"] = str(exc)[:500]
            result = {"status": "failed", "error": str(exc)[:500]}
    remote = _remote_status(config, settings)
    section["pve_maintenance"] = {key: remote.get(key) for key in ("status", "finished_at", "snapshot_count", "repo_bytes", "check", "breaker", "latest_snapshot_at") if key in remote}
    section["alerts"] = assess(section, remote, now=datetime.now(UTC), max_age_hours=max_age)
    record_section("pve_copy", section)
    return {**result, "alerts": section["alerts"]}
