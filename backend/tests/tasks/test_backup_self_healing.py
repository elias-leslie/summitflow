"""Backups recover from killed runs and restarts, bound their scratch, and alert once."""

from __future__ import annotations

import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from unittest.mock import MagicMock

import pytest

from app.tasks import backup_alerts as alerts
from app.tasks import backup_lock
from app.tasks import backup_scheduler as scheduler

REAL_SOURCE_STATUSES = alerts._source_statuses
REAL_CAPACITY_CONDITIONS = alerts._capacity_conditions


def _dead_pid() -> int:
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


# --- graceful stop: Restic gets SIGINT so it can remove its own lock -------


def test_stopped_process_is_interrupted_before_kill(tmp_path, monkeypatch):
    from app.tasks import backup_activity

    marker = tmp_path / "interrupted"
    script = (
        "import signal, sys, time\n"
        f"signal.signal(signal.SIGINT, lambda *_: (open({str(marker)!r}, 'w').write('lock released'), sys.exit(130)))\n"
        "time.sleep(60)\n"
    )
    activity = MagicMock()
    calls = {"n": 0}

    def cancel():
        calls["n"] += 1
        if calls["n"] > 2:
            raise backup_activity.BackupCancelled("Cancelled by owner")

    activity.check_cancelled.side_effect = cancel
    monkeypatch.setattr(backup_activity, "current_activity", lambda: activity)
    monkeypatch.setattr(backup_activity, "CONTROL_POLL_SECONDS", 0.2)
    with pytest.raises(backup_activity.BackupCancelled):
        backup_activity.run_bulk_process([sys.executable, "-c", script])
    assert marker.read_text() == "lock released"


def test_process_ignoring_interrupt_is_killed_after_grace(monkeypatch):
    from app.tasks import backup_activity

    proc = subprocess.Popen(
        [sys.executable, "-c", "import signal, time; signal.signal(signal.SIGINT, signal.SIG_IGN); time.sleep(60)"],
        start_new_session=True,
    )
    time.sleep(0.3)
    monkeypatch.setattr(backup_activity, "STOP_GRACE_SECONDS", 0.3)
    started = time.monotonic()
    backup_activity._stop_process_group(proc)
    assert proc.returncode == -signal.SIGKILL
    assert time.monotonic() - started < 5


# --- leases: a dead worker's lease is taken over at once -------------------


def test_lease_from_dead_local_process_is_dead_but_live_or_foreign_is_not():
    host = socket.gethostname()
    pid = os.getpid()
    live = f"{'a' * 32}|{pid}|{backup_lock._process_start(pid)}|{host}"
    assert backup_lock.lease_holder_dead(live) is False
    assert backup_lock.lease_holder_dead(f"{'a' * 32}|{_dead_pid()}|123|{host}") is True
    assert backup_lock.lease_holder_dead(f"{'a' * 32}|{pid}|1|{host}") is True  # PID reused by another process
    assert backup_lock.lease_holder_dead(f"{'a' * 32}|{_dead_pid()}|123|other-host") is False
    assert backup_lock.lease_holder_dead("a" * 32) is False  # legacy token format
    assert backup_lock.lease_holder_dead(MagicMock()) is False


class FakeRedis:
    def __init__(self):
        self.values: dict[str, Any] = {}

    def get(self, key):
        return self.values.get(key)

    def exists(self, key):
        return int(key in self.values)

    def eval(self, script, count, *args):
        key = args[0]
        if "del" in script:
            if self.values.get(key) == args[1]:
                del self.values[key]
                return 1
            return 0
        if "set" in script:
            if args[1] in self.values or key in self.values:
                return None
            self.values[key] = args[2]
            return True
        raise AssertionError(script)


def test_acquire_takes_over_dead_holder_lease_but_not_live_one(monkeypatch):
    redis = FakeRedis()
    monkeypatch.setattr(backup_lock, "get_redis", lambda: redis)
    key = backup_lock._lock_key("fixture")
    redis.values[key] = f"{'b' * 32}|{_dead_pid()}|123|{socket.gethostname()}"
    assert backup_lock.has_active_backup_lease("fixture") is False
    assert backup_lock.backup_lease_holder_dead("fixture") is True
    token = backup_lock.acquire_backup_lock("fixture")
    assert token is not None and redis.values[key] == token
    assert backup_lock.has_active_backup_lease("fixture") is True
    assert backup_lock.acquire_backup_lock("fixture") is None  # live holder keeps it


def test_restart_guard_ignores_dead_holder_leases(monkeypatch):
    redis = MagicMock()
    redis.set.return_value = True
    dead = f"{'c' * 32}|{_dead_pid()}|1|{socket.gethostname()}"
    redis.scan_iter.return_value = [f"{backup_lock.BACKUP_LOCK_PREFIX}dead-source".encode()]
    redis.get.side_effect = lambda key: dead if key.endswith("dead-source") else None
    monkeypatch.setattr(backup_lock, "get_redis", lambda: redis)
    monkeypatch.setattr(backup_lock, "owns_backup_lease", lambda *_: True)
    monkeypatch.setattr(backup_lock, "renew_backup_lock", lambda *_: True)
    monkeypatch.setattr(backup_lock, "release_backup_lock", lambda *_: True)
    with backup_lock.backup_worker_restart_guard() as assert_owned:
        assert_owned()


# --- scheduler housekeeping runs every tick --------------------------------


def test_dead_holder_rows_are_reaped_without_waiting_thirty_minutes(monkeypatch):
    calls: list[tuple[int, str]] = []

    def fail(*, max_age_minutes, is_source_active, error_message=None):
        calls.append((max_age_minutes, str(error_message)))
        return 1 if max_age_minutes == scheduler.DEAD_HOLDER_AGE_MINUTES and not is_source_active("killed") else 0

    monkeypatch.setattr(scheduler.backup_store, "fail_stale_running_backups", fail)
    monkeypatch.setattr(scheduler, "backup_lease_holder_dead", lambda source_id: source_id == "killed")
    assert scheduler._fail_stale_running_records() == 1
    assert [age for age, _ in calls] == [scheduler.STALE_RUNNING_AGE_MINUTES, scheduler.DEAD_HOLDER_AGE_MINUTES]
    assert "restart or kill" in calls[1][1]


def test_scratch_residue_is_reaped_only_when_old_and_unused(tmp_path, monkeypatch):
    monkeypatch.setattr(scheduler, "SCRATCH_ROOT", tmp_path)
    parent = tmp_path / f"st-backups-{os.getuid()}"
    old, recent, open_job = (parent / name for name in ("restic-prune-cache-old", "restic-process-new", "restic-open"))
    for job in (old, recent, open_job):
        (job / "cache").mkdir(parents=True)
        (job / "cache" / "pack").write_bytes(b"x" * 10)
    stale = time.time() - (scheduler.SCRATCH_RESIDUE_HOURS + 1) * 3600
    for job in (old, open_job):
        for path in (job, job / "cache", job / "cache" / "pack"):
            os.utime(path, (stale, stale))
    monkeypatch.setattr(scheduler, "_open_paths", lambda: {open_job / "cache" / "pack"})
    result = scheduler._reap_backup_scratch()
    assert result == {"removed": 1, "bytes": 10}
    assert not old.exists() and recent.exists() and open_job.exists()


def test_leaked_isolated_acceptance_clone_is_reaped_by_age(tmp_path, monkeypatch):
    monkeypatch.setattr(scheduler, "SCRATCH_ROOT", tmp_path)
    parent = tmp_path / f"st-acceptance-{os.getuid()}"
    leaked, running = parent / "st-a-killed", parent / "st-a-running"
    for clone in (leaked, running):
        (clone / "source").mkdir(parents=True)
        (clone / "source" / "app.py").write_bytes(b"x" * 7)
    stale = time.time() - (scheduler.SCRATCH_RESIDUE_HOURS + 1) * 3600
    for path in (leaked, leaked / "source", leaked / "source" / "app.py"):
        os.utime(path, (stale, stale))
    monkeypatch.setattr(scheduler, "_open_paths", set)
    assert scheduler._reap_backup_scratch() == {"removed": 1, "bytes": 7}
    assert not leaked.exists() and running.exists()


def test_outside_window_tick_still_heals_and_alerts(monkeypatch):
    from app.tasks import backup_repository_runtime as runtime

    monkeypatch.setattr(scheduler, "_scheduled_host_backup", lambda _: {"status": "skipped"})
    monkeypatch.setattr(scheduler, "_scheduled_backup_window_open", lambda _now: False)
    monkeypatch.setattr(scheduler.backup_store, "list_due_sources", lambda: [])
    monkeypatch.setattr(runtime, "sync_repository_batch", lambda batch: {"pair": {"status": "pending", "error": "restic copy failed to lock repository (exit 11)"}})
    healed: list[str] = []
    monkeypatch.setattr(scheduler, "_fail_stale_running_records", lambda: healed.append("rows") or 2)
    monkeypatch.setattr(scheduler, "_reap_backup_scratch", lambda: healed.append("scratch") or {"removed": 0, "bytes": 0})
    seen: list[dict[str, Any]] = []
    monkeypatch.setattr(alerts, "evaluate_backup_alerts", lambda summary: seen.append(summary) or {"active": ["offsite-copy:x"]})
    result = scheduler.run_scheduled_backups()
    assert healed == ["rows", "scratch"]
    assert result["housekeeping"]["stale_failed"] == 2
    assert result["repository_copy"]["pair"]["error"].startswith("restic copy failed")
    assert seen and result["alerts"] == {"active": ["offsite-copy:x"]}


# --- alerts: one notification per condition, cleared on recovery -----------


class AlertStore:
    def __init__(self):
        self.notifications: list[dict[str, Any]] = []
        self.dismissed: list[str] = []

    def create(self, **kwargs):
        item = {"id": f"notif-{len(self.notifications)}", **kwargs, "status": "pending"}
        self.notifications.append(item)
        return item

    def dismiss(self, notification_id):
        self.dismissed.append(notification_id)
        for item in self.notifications:
            if item["id"] == notification_id:
                item["status"] = "dismissed"

    def latest(self):
        result: dict[str, dict[str, Any]] = {}
        for item in self.notifications:
            meta = item["metadata"]
            result[meta["backup_alert"]] = {"id": item["id"], "event": meta["backup_alert_event"], "fingerprint": meta["backup_alert_fingerprint"],
                                            "status": item["status"], "title": item["title"], "message": item["message"], "created_at": None}
        return result


@pytest.fixture
def alert_store(monkeypatch, tmp_path):
    store = AlertStore()
    monkeypatch.setattr(alerts, "create_notification", store.create)
    monkeypatch.setattr(alerts, "dismiss_notification", store.dismiss)
    monkeypatch.setattr(alerts.backup_store, "latest_backup_alerts", store.latest)
    monkeypatch.setattr(alerts, "SOURCES_RECEIPT", tmp_path / "backup-freshness/sources.json")
    monkeypatch.setattr(alerts, "_source_statuses", lambda now: {})
    monkeypatch.setattr(alerts, "_capacity_conditions", lambda summary: {})
    monkeypatch.setattr(alerts, "_proxmox_conditions", lambda now: {})
    return store


NOW = datetime(2026, 10, 11, 15, 0, tzinfo=UTC)


def _journal(pending_hours: float | None, *, error: str | None = None, prune_failures: int = 0, pruned_days: float = 1) -> dict[str, Any]:
    completed = (NOW - timedelta(hours=pending_hours or 0)).isoformat()
    return {
        "sources": {"s": {"snapshot_id": "snap", "completed_at": completed}},
        "offsite": {"pending_snapshot_ids": ["snap"] if pending_hours is not None else [], "error": error, "verified_at": completed},
        "maintenance": {
            "last_run_at": NOW.isoformat(),
            "local": {"pruned_at": (NOW - timedelta(days=pruned_days)).isoformat(), "prune_failures": 0},
            "remote": {"pruned_at": (NOW - timedelta(days=pruned_days)).isoformat(), "prune_failures": prune_failures},
            "result": {"remote": {"prune": {"status": "failed", "error": "restic maintenance failed (exit 130)"}}},
        },
    }


def _use_journal(monkeypatch, journal):
    from app.tasks import backup_repository_runtime as runtime

    monkeypatch.setattr(alerts, "_restic_backends", lambda: [("stb-fixture", {"RESTIC_REMOTE_REPOSITORY": "rclone:x:y"})])
    monkeypatch.setattr(runtime, "repository_journal", lambda env: journal)


def test_pending_copy_alert_fires_once_with_real_error_and_clears(monkeypatch, alert_store):
    error = "restic verification failed to lock repository (exit 11)"
    _use_journal(monkeypatch, _journal(3, error=error))
    assert alerts.evaluate_backup_alerts({}, now=NOW)["raised"] == []  # within 6h

    _use_journal(monkeypatch, _journal(18, error=error))
    first = alerts.evaluate_backup_alerts({}, now=NOW)
    second = alerts.evaluate_backup_alerts({}, now=NOW + timedelta(hours=1))
    assert first["raised"] == ["offsite-copy:stb-fixture"] and second["raised"] == []
    assert len(alert_store.notifications) == 1
    assert error in alert_store.notifications[0]["message"]
    assert alert_store.notifications[0]["severity"] == "error"

    _use_journal(monkeypatch, _journal(None))
    cleared = alerts.evaluate_backup_alerts({}, now=NOW + timedelta(hours=2))
    assert cleared["cleared"] == ["offsite-copy:stb-fixture"]
    assert alert_store.notifications[-1]["severity"] == "info"
    assert alert_store.dismissed == ["notif-0"]
    assert alerts.evaluate_backup_alerts({}, now=NOW + timedelta(hours=3)) == {"active": [], "raised": [], "cleared": []}


def test_pending_copy_without_recorded_error_never_reports_null(monkeypatch, alert_store):
    _use_journal(monkeypatch, _journal(10))
    alerts.evaluate_backup_alerts({"repository_copy": {"pair": {"status": "pending", "error": None, "reason": "insufficient-copy-headroom"}}}, now=NOW)
    assert "insufficient-copy-headroom" in alert_store.notifications[0]["message"]


def test_copy_error_persists_across_runs_and_clears_on_verified_copy(monkeypatch, alert_store, tmp_path):
    from app.tasks import backup_repository_runtime as runtime

    state: dict[str, Any] = {"offsite": {}}
    runtime._record_copy_outcome(tmp_path, state, {"status": "pending", "error": "rclone: drive quota exceeded"})
    assert state["offsite"]["last_copy_error"]["error"] == "rclone: drive quota exceeded"

    # A later run evaluates without this run's copy result and still names the error.
    journal = _journal(10)
    journal["offsite"]["last_copy_error"] = state["offsite"]["last_copy_error"]
    _use_journal(monkeypatch, journal)
    alerts.evaluate_backup_alerts({}, now=NOW)
    assert "rclone: drive quota exceeded" in alert_store.notifications[0]["message"]

    runtime._record_copy_outcome(tmp_path, state, {"status": "verified"})
    assert "last_copy_error" not in state["offsite"]


def test_prune_alerts_after_more_than_two_failed_runs_and_when_overdue(monkeypatch, alert_store):
    _use_journal(monkeypatch, _journal(None, prune_failures=2))
    assert alerts.evaluate_backup_alerts({}, now=NOW)["active"] == []
    _use_journal(monkeypatch, _journal(None, prune_failures=3))
    assert alerts.evaluate_backup_alerts({}, now=NOW)["raised"] == ["prune:stb-fixture:remote"]
    assert "exit 130" in alert_store.notifications[-1]["message"]
    _use_journal(monkeypatch, _journal(None, pruned_days=20))
    overdue = alerts.evaluate_backup_alerts({}, now=NOW)
    assert sorted(overdue["active"]) == ["prune:stb-fixture:local", "prune:stb-fixture:remote"]
    assert "overdue" in alert_store.notifications[-1]["title"]


def test_stale_sources_alert_names_each_source_and_its_error(monkeypatch, alert_store):
    monkeypatch.setattr(alerts, "_source_statuses", REAL_SOURCE_STATUSES)
    monkeypatch.setattr(alerts, "_restic_backends", lambda: [])
    sources = [
        {"id": "fresh", "frequency": "four_hourly", "created_at": "2026-01-01T00:00:00+00:00"},
        {"id": "stale", "frequency": "four_hourly", "created_at": "2026-01-01T00:00:00+00:00"},
        {"id": "new", "frequency": "daily", "created_at": (NOW - timedelta(hours=2)).isoformat()},
        {"id": "parked", "frequency": "four_hourly", "created_at": "2026-01-01T00:00:00+00:00"},
    ]
    health = [
        {"source_id": "fresh", "enabled": True, "last_success_at": NOW - timedelta(hours=3)},
        {"source_id": "stale", "enabled": True, "last_success_at": NOW - timedelta(hours=9)},
        {"source_id": "new", "enabled": True, "last_success_at": None},
        {"source_id": "off", "enabled": False, "last_success_at": None},
        {"source_id": "parked", "enabled": True, "last_success_at": NOW - timedelta(days=3)},
    ]
    # The owner powered the parked guest off; its scheduler run marked it offline.
    monkeypatch.setattr(alerts, "source_offline_since", lambda source_id: NOW.isoformat() if source_id == "parked" else None)
    monkeypatch.setattr(alerts.backup_store, "list_sources", lambda: sources)
    monkeypatch.setattr(alerts.backup_store, "get_backup_health_summary", lambda: health)
    monkeypatch.setattr(alerts.backup_store, "list_backups", lambda **_: ([{"status": "failed", "error_message": "Capture blocked: insufficient host-policy headroom"}], 1))
    result = alerts.evaluate_backup_alerts({}, now=NOW)
    assert result["raised"] == ["sources-stale"]
    message = alert_store.notifications[0]["message"]
    assert "stale (last success 9h ago; Capture blocked" in message and "fresh" not in message and "new" not in message
    assert "parked" not in message


def test_sources_receipt_publishes_per_source_freshness_and_refusal_streak(monkeypatch, alert_store):
    import json

    monkeypatch.setattr(alerts, "_source_statuses", REAL_SOURCE_STATUSES)
    monkeypatch.setattr(alerts, "_restic_backends", lambda: [])
    monkeypatch.setattr(alerts, "source_offline_since", lambda source_id: None)
    monkeypatch.setattr(alerts.backup_store, "list_sources", lambda: [
        {"id": "fresh", "frequency": "daily", "created_at": "2026-01-01T00:00:00+00:00"},
        {"id": "stale", "frequency": "daily", "created_at": "2026-01-01T00:00:00+00:00"}])
    monkeypatch.setattr(alerts.backup_store, "get_backup_health_summary", lambda: [
        {"source_id": "fresh", "enabled": True, "last_success_at": NOW - timedelta(hours=3), "last_backup_status": "completed"},
        {"source_id": "stale", "enabled": True, "last_success_at": NOW - timedelta(days=3), "last_backup_status": "failed"}])
    monkeypatch.setattr(alerts.backup_store, "list_backups", lambda **_: ([{"status": "failed", "error_message": "Capture blocked: insufficient host-policy headroom"}], 1))
    refused = {"results": [{"source_id": "stale", "error": "Capture blocked: insufficient host-policy headroom"}]}
    monkeypatch.setattr(alerts, "_capacity_conditions", REAL_CAPACITY_CONDITIONS)
    monkeypatch.setenv("SF_HOST_RETENTION_PRESSURE_MIN_FREE_GB", "0")
    alerts.evaluate_backup_alerts(refused, now=NOW)
    first = json.loads(alerts.SOURCES_RECEIPT.read_text())
    assert first["ok"] is False and first["capture_refused"] is True and first["capture_refused_since"] == NOW.isoformat()
    assert {item["key"] for item in first["conditions"]} == {"sources-stale", "capacity"}
    assert first["sources"]["fresh"] == {"ok": True, "frequency": "daily", "stale_after_hours": 48.0,
                                         "last_success_at": (NOW - timedelta(hours=3)).isoformat(), "last_status": "completed",
                                         "offline_since": None, "last_error": None}
    assert first["sources"]["stale"]["ok"] is False and "insufficient host-policy headroom" in first["sources"]["stale"]["last_error"]
    # The streak start survives later runs and clears once capture resumes.
    alerts.evaluate_backup_alerts(refused, now=NOW + timedelta(hours=1))
    assert json.loads(alerts.SOURCES_RECEIPT.read_text())["capture_refused_since"] == NOW.isoformat()
    alerts.evaluate_backup_alerts({}, now=NOW + timedelta(hours=2))
    last = json.loads(alerts.SOURCES_RECEIPT.read_text())
    assert last["capture_refused"] is False and last["capture_refused_since"] is None


def test_capacity_alert_on_refused_capture_or_low_free_space(monkeypatch, alert_store, tmp_path):
    monkeypatch.setattr(alerts, "_capacity_conditions", REAL_CAPACITY_CONDITIONS)
    monkeypatch.setattr(alerts, "_restic_backends", lambda: [])
    monkeypatch.setattr(alerts, "SCRATCH_ROOT", tmp_path)
    monkeypatch.setenv("SF_HOST_RETENTION_PRESSURE_MIN_FREE_GB", "0")
    refused = {"results": [{"source_id": "big", "status": "failed", "error": "Capture blocked: insufficient host-policy headroom"}]}
    assert alerts.evaluate_backup_alerts(refused, now=NOW)["raised"] == ["capacity"]
    assert "capture refused for big" in alert_store.notifications[0]["message"]
    assert alerts.evaluate_backup_alerts({}, now=NOW)["cleared"] == ["capacity"]
    monkeypatch.setenv("SF_HOST_RETENTION_PRESSURE_MIN_FREE_GB", "1000000")
    assert alerts.evaluate_backup_alerts({}, now=NOW)["raised"] == ["capacity"]
    assert "GB free" in alert_store.notifications[-1]["message"]


# --- the 25 GB free-space floor at its default value ------------------------


def test_free_space_floor_defaults_to_25_gb_for_admission_and_alerts(monkeypatch, alert_store, tmp_path):
    from types import SimpleNamespace

    from app.tasks import backup_repository_runtime as runtime
    from app.utils.host_retention_policy import HostRetentionPolicy

    monkeypatch.delenv("SF_HOST_RETENTION_PRESSURE_MIN_FREE_GB", raising=False)
    floor = 25 * 1024**3
    assert HostRetentionPolicy.from_env().pressure_min_free_gb == 25.0
    usage = shutil.disk_usage(tmp_path)
    free = {"bytes": floor}
    monkeypatch.setattr(runtime.shutil, "disk_usage", lambda _path: usage._replace(total=10 * floor, used=floor, free=free["bytes"]))
    monkeypatch.setattr(alerts.shutil, "disk_usage", lambda _path: usage._replace(total=10 * floor, used=floor, free=free["bytes"]))
    config = cast("Any", SimpleNamespace(local_repository=tmp_path))
    needed = 1024**2
    state = {"sources": {"s": {"result": {"stored_bytes": needed}}}}
    free["bytes"] = floor + needed
    admission = runtime._capacity_admission(config, state, "s", staging_directory=tmp_path, streamed=True)
    assert admission["admitted"] is True and admission["filesystems"][0]["reserve_bytes"] == floor
    free["bytes"] = floor + needed - 1
    assert runtime._capacity_admission(config, state, "s", staging_directory=tmp_path, streamed=True)["admitted"] is False

    monkeypatch.setattr(alerts, "_capacity_conditions", REAL_CAPACITY_CONDITIONS)
    monkeypatch.setattr(alerts, "_restic_backends", lambda: [])
    monkeypatch.setattr(alerts, "SCRATCH_ROOT", tmp_path)
    free["bytes"] = floor
    assert alerts.evaluate_backup_alerts({}, now=NOW)["raised"] == []
    free["bytes"] = floor - 1
    assert alerts.evaluate_backup_alerts({}, now=NOW)["raised"] == ["capacity"]
