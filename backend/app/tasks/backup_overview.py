"""What the backups are doing, in one shape for the UI, ``st backup`` and the health alerts.

Two recovery layers, both written by ``backup_run``:

* local: btrbk points on the T7, every 4 hours, kept by its own daily retention;
* off-site: one daily restic job into the Google Drive repository, read from the
  btrbk snapshots of that run.

Everything older (the per-project sources, the restic repository on the T7) is
shown only as "old, ageing out" so the owner can see what could be deleted.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from ..logging_config import get_logger
from ..storage import backups as backup_store
from . import backup_btrbk as host
from . import backup_offsite as offsite

logger = get_logger(__name__)

LOCAL_INTERVAL = timedelta(hours=4)
# A recovery point is reported missing only after the job has had several scheduled runs, with its own self-repair, to make one.
LOCAL_MISSING_AFTER = timedelta(hours=26)
OFFSITE_MISSING_AFTER = timedelta(hours=48)
PROXMOX_MISSING_AFTER = timedelta(hours=48)
CHECK_FAILURES_BEFORE_PROBLEM = 2  # the read-back runs weekly: two in a row
TIMER = "summitflow-host-backup.timer"


def _parse(value: Any) -> datetime | None:
    return offsite._parse(value)


def _ago(when: datetime | None, now: datetime) -> str:
    if when is None:
        return "never"
    hours = (now - when).total_seconds() / 3600
    return f"{hours:.0f} hours ago" if hours < 48 else f"{hours / 24:.0f} days ago"


def next_timer_run() -> str | None:
    """When systemd will start the next run, or None when the timer is not installed."""
    try:
        out = subprocess.run(["systemctl", "--user", "show", TIMER, "-p", "NextElapseUSecRealtime", "--value"], capture_output=True, text=True,
                             timeout=10, check=False).stdout.strip()
        if not out or out == "n/a":
            return None
        return datetime.strptime(out.rsplit(" ", 1)[0], "%a %Y-%m-%d %H:%M:%S").astimezone().astimezone(UTC).isoformat()
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def local_summary(*, points: bool = False) -> dict[str, Any]:
    """The btrbk layer, from its receipts. ``points`` also lists the T7 (a root helper call)."""
    try:
        last = host._receipt() or {}
    except (OSError, ValueError):
        last = {}
    good_path = host._state_root() / "last-good.json"
    try:
        good = json.loads(good_path.read_text()) if good_path.is_file() else {}
    except (OSError, ValueError):
        good = {}
    summary: dict[str, Any] = {
        "engine": "btrbk", "enabled": host._enabled(), "schedule": "every 4 hours", "keeps": "7 days",
        "retention": "One point for each of the last 7 days, plus the newest. The runs between are thinned away by btrbk itself.",
        "last_run": {key: last.get(key) for key in ("run_id", "status", "started_at", "finished_at", "error")} if last else None,
        "last_good_at": good.get("finished_at"), "next_run_at": next_timer_run(), "target": None, "points": None,
    }
    try:
        usage = shutil.disk_usage(host.NATIVE_TARGET)
        summary["target"] = {"path": str(host.NATIVE_TARGET), "free_bytes": usage.free, "used_bytes": usage.used, "total_bytes": usage.total}
    except OSError:
        pass
    if points:
        try:
            names = [Path(path).name.split(".", 1)[0] for path in host._native_listing(host.NATIVE_TARGET, "target")]
            summary["points"] = {name: names.count(name) for name in sorted(set(names))}
        except Exception:
            logger.warning("backup_overview_points_unavailable")
    return summary


def offsite_summary() -> dict[str, Any]:
    state = offsite.read_state()
    run = state.get("current_run") or None
    jobs = state.get("jobs") or {}
    summary: dict[str, Any] = {
        "engine": "restic", "schedule": "daily", "repository": state.get("repository"),
        "last_attempt_at": state.get("last_attempt_at"), "last_success_at": state.get("last_success_at"), "status": state.get("last_status"),
        "error": state.get("last_error"), "running": {"started_at": run.get("started_at")} if run and state.get("last_status") == "running" else None,
        "jobs": jobs, "check": state.get("check"), "spot_restore": state.get("spot_restore"),
        "maintenance": state.get("maintenance"), "runs": state.get("runs") or [],
    }
    return summary


def legacy_summary() -> dict[str, Any]:
    """What the retired shape left behind. Nothing here is written to any more."""
    state = offsite.read_state()
    legacy = state.get("legacy") or {}
    sources = [source for source in backup_store.list_sources() if not source.get("enabled")]
    return {
        "local_repository": {"path": legacy.get("local_repository_path"), "bytes": legacy.get("local_repository_bytes"),
                             "note": "The old restic repository on the T7. Nothing writes to it any more; the owner can delete it."},
        "drive_snapshots": {"count": legacy.get("drive_snapshots"), "ages_out_after_days": offsite.get_settings().backup_offsite_legacy_days,
                            "note": "Per-project snapshots from before the daily job. They age out on their own."},
        "retired_sources": len(sources),
    }


def health_problems(now: datetime | None = None) -> list[dict[str, str]]:
    """Real problems only: a recovery point that is actually missing, or a failed Drive check. Slow runs are not problems."""
    now = now or datetime.now(UTC)
    problems: list[dict[str, str]] = []
    local = local_summary()
    if local["enabled"]:
        good = _parse(local["last_good_at"])
        if good is None or now - good > LOCAL_MISSING_AFTER:
            error = (local.get("last_run") or {}).get("error")
            problems.append({"key": "local-missing", "title": "No recent local backup point",
                             "message": f"The last good local backup point was {_ago(good, now)}; it runs every 4 hours." + (f" Last error: {error}" if error else "")})
    state = offsite.read_state()
    success = _parse(state.get("last_success_at"))
    first = _parse(state.get("first_attempt_at")) or _parse((state.get("runs") or [{}])[0].get("started_at"))
    if (success is None and first is not None and now - first > OFFSITE_MISSING_AFTER) or (success is not None and now - success > OFFSITE_MISSING_AFTER):
        problems.append({"key": "offsite-missing", "title": "No recent Google Drive backup",
                         "message": f"The last good Google Drive backup was {_ago(success, now)}; it runs daily and retries on every scheduled run. Last error: {state.get('last_error') or 'none recorded'}"})
    check = state.get("check") or {}
    if int(check.get("failures") or 0) >= CHECK_FAILURES_BEFORE_PROBLEM:
        problems.append({"key": "offsite-check", "title": "Google Drive backup check is failing",
                         "message": f"The data check of the Google Drive repository failed {check['failures']} weeks in a row. Last error: {check.get('error')}"})
    spot = state.get("spot_restore") or {}
    if spot.get("status") == "failed" and int(spot.get("failures") or 0) >= CHECK_FAILURES_BEFORE_PROBLEM:
        problems.append({"key": "offsite-spot-restore", "title": "Test restore from Google Drive failed",
                         "message": f"The weekly test restore did not match what was backed up {spot['failures']} weeks in a row: {spot.get('error')}"})
    maintenance = state.get("maintenance") or {}
    pruned = _parse(maintenance.get("pruned_at"))
    if pruned is not None and now - pruned > timedelta(days=21) and maintenance.get("prune_error"):
        problems.append({"key": "offsite-prune", "title": "Google Drive backup cleanup keeps failing",
                         "message": f"The Drive repository has not been cleaned up since {pruned.date()}. Last error: {maintenance['prune_error']}"})
    return problems


def freshness_sources(now: datetime) -> dict[str, dict[str, Any]]:
    """Per-source freshness for Nightshift's sources.json: the two layers, then each stream/directory/Proxmox job."""
    local = local_summary()
    state = offsite.read_state()
    sources: dict[str, dict[str, Any]] = {}
    good = _parse(local["last_good_at"])
    last_run = local.get("last_run") or {}
    sources["host-btrbk"] = {
        "ok": bool(good and now - good <= LOCAL_MISSING_AFTER), "frequency": "four_hourly", "stale_after_hours": LOCAL_MISSING_AFTER.total_seconds() / 3600,
        "last_success_at": good.isoformat() if good else None, "last_status": last_run.get("status"), "offline_since": None,
        "last_error": last_run.get("error") if last_run.get("status") not in (None, "completed") else None,
    }
    success = _parse(state.get("last_success_at"))
    # Same rule as health_problems: the very first copy gets a full window to land before it counts as missing.
    reference = success or _parse(state.get("first_attempt_at"))
    sources["offsite-restic"] = {
        "ok": reference is None or now - reference <= OFFSITE_MISSING_AFTER, "frequency": "daily", "stale_after_hours": OFFSITE_MISSING_AFTER.total_seconds() / 3600,
        "last_success_at": success.isoformat() if success else None, "last_status": state.get("last_status"), "offline_since": None,
        "last_error": state.get("last_error"),
    }
    for name, job in sorted((state.get("jobs") or {}).items()):
        if name in offsite.SUBVOLUME_JOBS or name in offsite.STREAM_JOBS:
            continue
        when = _parse(job.get("time"))
        sources[name] = {"ok": bool(when and now - when <= PROXMOX_MISSING_AFTER), "frequency": "daily", "stale_after_hours": PROXMOX_MISSING_AFTER.total_seconds() / 3600,
                         "last_success_at": when.isoformat() if when else None, "last_status": job.get("status"), "offline_since": None, "last_error": None}
    return sources


def offsite_runs(state: dict[str, Any]) -> dict[str, Any]:
    """The Drive job's own time window and remote, so a bandwidth alert on rclone can be matched to a backup that is running."""
    last = state.get("last_run") or {}
    running = state.get("current_run") if state.get("last_status") == "running" else None
    remote = str(state.get("repository") or "")
    remote = remote.removeprefix("rclone:").split(":", 1)[0] if remote.startswith("rclone:") else None
    return {"remote": remote, "active": {"started_at": running.get("started_at")} if running else None,
            "last": {"started_at": last.get("started_at"), "finished_at": last.get("finished_at"), "status": last.get("status")} if last else None}


def overview(*, points: bool = False, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    problems = health_problems(now)
    return {"generated_at": now.isoformat(), "ok": not problems, "problems": problems,
            "local": local_summary(points=points), "offsite": offsite_summary(), "legacy": legacy_summary()}
