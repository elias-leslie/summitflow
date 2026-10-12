"""Backup health: check freshness every tick; weekly drop detection and a PVE-copy test restore.

``refresh_check_status`` writes the ``restic_checks`` section from the
existing daily rotating ``restic check --read-data-subset`` results rather
than reading data twice. ``run_weekly_health`` writes the ``health`` section: it compares snapshot count and repository size with
last week's, and restores one small recent snapshot from the append-only PVE
copy into disposable scratch to prove the third copy is usable.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from ..logging_config import get_logger
from ..utils.transient_scratch import disposable_scratch
from .backup_activity import run_bulk_process
from .backup_pve_copy import _env, _settings, restic_command
from .backup_restic import ResticAdapter, ResticConfig
from .backup_safety import read_status, record_section

logger = get_logger(__name__)

CADENCE = timedelta(days=7)
CHECK_MAX_AGE = timedelta(days=3)
COUNT_DROP_FRACTION = 0.10
BYTES_DROP_FRACTION = 0.25
RESTORE_SOURCES = ("claude-user-config", "agent-skills", "codex-config")


def drops(previous: Mapping[str, Any], count: int, size: int) -> list[dict[str, str]]:
    alerts = []
    before_count, before_size = previous.get("snapshot_count"), previous.get("repository_bytes")
    if isinstance(before_count, int) and before_count - count > 10 and (before_count - count) / before_count > COUNT_DROP_FRACTION:
        alerts.append({"kind": "snapshot-count-drop", "message": f"Local snapshots fell from {before_count} to {count} in a week"})
    if isinstance(before_size, int) and before_size and (before_size - size) / before_size > BYTES_DROP_FRACTION:
        alerts.append({"kind": "repository-size-drop", "message": f"Local repository shrank from {before_size / 1024**3:.1f} GB to {size / 1024**3:.1f} GB in a week"})
    return alerts


def check_alerts(maintenance: Mapping[str, Any], now: datetime) -> tuple[dict[str, Any], list[dict[str, str]]]:
    summary, alerts = {}, []
    for label in ("local", "remote"):
        result = (maintenance.get(label) or {}).get("monthly_result") or {}
        checked = result.get("checked_at")
        summary[label] = {key: result.get(key) for key in ("status", "bucket", "checked_at", "coverage_complete")}
        if result.get("verified") is False or result.get("status") == "failed":
            alerts.append({"kind": f"{label}-check-failed", "message": f"The {label} restic data check failed: {result.get('error') or 'see backup readiness'}"})
        elif not checked or now - datetime.fromisoformat(str(checked)) > CHECK_MAX_AGE:
            alerts.append({"kind": f"{label}-check-stale", "message": f"The {label} restic data check has not passed since {checked or 'ever'}"})
    return summary, alerts


def _pve_test_restore(config: ResticConfig) -> dict[str, Any]:
    settings = _settings(config)
    if settings is None:
        return {"status": "skipped", "reason": "pve-copy-not-configured"}
    for source in RESTORE_SOURCES:
        listing = run_bulk_process(restic_command(config, settings, "snapshots", "--json", "--latest", "1", "--tag", f"source:{source}"),
                                   env=_env(), phase="health", object_name="PVE copy snapshots")
        snapshots = json.loads(listing.stdout or "[]") if listing.returncode == 0 else []
        if not snapshots:
            continue
        snapshot = snapshots[-1]
        with disposable_scratch("pve-test-restore-") as scratch:
            target = scratch / "restore"
            target.mkdir(mode=0o700)
            proc = run_bulk_process(restic_command(config, settings, "restore", snapshot["id"], "--target", str(target), "--verify"),
                                    env=_env(), phase="health", object_name="PVE copy test restore")
            files = sum(1 for path in target.rglob("*") if path.is_file())
        ok = proc.returncode == 0 and files > 0
        return {"status": "verified" if ok else "failed", "source_id": source, "snapshot_id": snapshot["id"],
                "snapshot_time": snapshot.get("time"), "files": files}
    return {"status": "failed", "reason": "no-restorable-snapshot"}


def refresh_check_status(env: Mapping[str, str], *, now: datetime | None = None) -> dict[str, Any]:
    """Every tick: alert while the latest daily restic data check failed or went stale."""
    from .backup_repository_runtime import repository_journal

    section: dict[str, Any] = {}
    try:
        section["checks"], section["alerts"] = check_alerts(repository_journal(dict(env)).get("maintenance") or {}, now or datetime.now(UTC))
    except Exception as exc:
        section["alerts"] = [{"kind": "journal-unreadable", "message": str(exc)[:300]}]
    record_section("restic_checks", section)
    return {"status": "alert" if section["alerts"] else "ok", "alerts": section["alerts"]}


def run_weekly_health(env: Mapping[str, str], *, force: bool = False, now: datetime | None = None) -> dict[str, Any]:
    current = now or datetime.now(UTC)
    previous = (read_status().get("sections") or {}).get("health") or {}
    last = previous.get("last_run_at")
    if not force and last and current - datetime.fromisoformat(str(last)) < CADENCE:
        return {"status": "skipped", "reason": "weekly-cadence"}
    config = ResticConfig.from_env(dict(env))
    adapter = ResticAdapter(config)
    section: dict[str, Any] = {"last_run_at": current.isoformat(), "alerts": []}
    try:
        count = len(adapter.snapshots())
        size = adapter.physical_bytes()
        section.update(snapshot_count=count, repository_bytes=size)
        section["alerts"] += drops(previous, count, size)
    except Exception as exc:
        section["alerts"].append({"kind": "inventory-failed", "message": f"Could not list the local repository: {exc}"})
    try:
        section["pve_test_restore"] = _pve_test_restore(config)
    except Exception as exc:
        section["pve_test_restore"] = {"status": "failed", "error": str(exc)[:300]}
    if section["pve_test_restore"].get("status") == "failed":
        section["alerts"].append({"kind": "pve-test-restore-failed", "message": f"Test restore from the PVE copy failed: {section['pve_test_restore']}"[:500]})
    record_section("health", section)
    logger.info("backup_weekly_health_completed", alerts=len(section["alerts"]))
    return {"status": "alert" if section["alerts"] else "ok", "alerts": section["alerts"]}
