"""Daily pilot contracts; synthetic interface evidence, no remote operations."""

from __future__ import annotations

import copy
import fcntl
import itertools
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest

from app.tasks import backup_repository_runtime as runtime
from app.tasks import backup_restic_pilot as pilot
from app.tasks import backup_scheduler as scheduler


def _sample(index: int = 0) -> dict:
    return {
        "timestamp": (datetime(2026, 9, 29, 2, tzinfo=UTC) + timedelta(seconds=index + 1)).isoformat(),
        "monotonic_ns": index + 1, "boot_id": "synthetic-boot",
        "interface": "enp8s0", "ifindex": "2", "iflink": "2", "address": "fixture",
        "device": "/sys/devices/fixture", "route_sha256": "fixture-route",
        "rx_bytes": 100 + index * 10, "tx_bytes": 200 + index * 20,
    }


@pytest.fixture
def configured(tmp_path, monkeypatch):
    monkeypatch.setattr(pilot.settings, "backup_restic_pilot_enabled", True)
    monkeypatch.setattr(pilot.settings, "backup_restic_pilot_backend_id", "stb-pilot")
    monkeypatch.setattr(pilot.settings, "backup_restic_pilot_daily_utc", "00:00")
    monkeypatch.setattr(pilot.settings, "backup_restic_pilot_interface", "enp8s0")
    monkeypatch.setattr(pilot, "backup_key_directory", lambda: tmp_path)
    backend = {"id": "stb-pilot", "enabled": True, "is_default": False, "backend_type": "local", "config": {"engine": "restic", "restic_remote_repository": "fixture-independent"}}
    monkeypatch.setattr(pilot.backup_store, "get_backend", lambda _: backend)
    sources = [{"id": "project", "enabled": True, "frequency": "weekly", "next_run": "unchanged", "last_run": "unchanged"}, {"id": "infrastructure", "enabled": True}, {"id": "retired", "enabled": False}]
    monkeypatch.setattr(pilot.backup_store, "list_sources", lambda: sources)
    rows = {
        source["id"]: {"source_id": source["id"], "storage_backend_id": "stb-pilot", "status": "completed", "verified": True, "verification_json": {"format": "restic-v1", "remote_snapshot_id": "remote-point", "remote_repository_id": "independent", "offsite": {"status": "verified"}}}
        for source in sources
    }
    monkeypatch.setattr(pilot.backup_store, "get_backup", lambda key: rows[key])
    monkeypatch.setattr(pilot.backup_store, "list_backups", lambda *, source_id, limit: ([rows[source_id]], 1))
    create = Mock(side_effect=lambda **options: {"status": "completed", "backup_id": options["source_id"]})
    monkeypatch.setattr(pilot, "create_backup", create)
    retry = Mock()
    monkeypatch.setattr(pilot, "sync_backup_offsite", retry)
    maintenance = Mock(return_value={"status": "completed", "remote": {"monthly": {"verified": True}, "prune": {"status": "preview"}}})
    monkeypatch.setattr(pilot, "maintain_repository", maintenance)
    counter = itertools.count()
    monkeypatch.setattr(pilot, "sample_interface", lambda _: _sample(next(counter)))
    history = Mock()
    monkeypatch.setattr(pilot.maintenance_store, "record_maintenance_run", history)
    return {"path": tmp_path / "restic-state" / "pilot.json", "sources": sources, "rows": rows, "create": create, "retry": retry, "maintenance": maintenance, "history": history, "backend": backend}


def test_default_pilot_is_disabled(configured, monkeypatch):
    monkeypatch.setattr(pilot.settings, "backup_restic_pilot_enabled", False)
    assert pilot.run_daily_restic_pilot()["reason"] == "pilot-disabled"
    assert not configured["path"].exists()
    configured["create"].assert_not_called()


def test_daily_capture_covers_every_enabled_source_leaves_native_schedule(configured, monkeypatch):
    update = Mock()
    monkeypatch.setattr(pilot.backup_store, "update_source_last_run", update)
    original = copy.deepcopy(configured["sources"])
    result = pilot.run_daily_restic_pilot()
    assert result["status"] == "completed"
    assert result["required_sources"] == ["infrastructure", "project"]
    assert result["coverage_verified"] is True
    assert result["seed"] is False
    assert result["missing_seed_sources"] == []
    assert configured["sources"] == original
    update.assert_not_called()
    assert {call.kwargs["source_id"] for call in configured["create"].call_args_list} == {"project", "infrastructure"}
    assert all(call.kwargs["storage_backend_id"] == "stb-pilot" for call in configured["create"].call_args_list)
    assert result["measurement"]["total_bytes"] == 90
    assert len(result["samples"]) == 2
    assert result["sample_count"] == 4
    assert len(result["sample_checkpoints"]) == 4
    assert result["measurement"]["attribution"] == "conservative-HOST-upper-bound"
    assert result["outside_operations_audited"] is False
    assert result["cutover_qualified"] is False
    assert configured["history"].call_args.args == (pilot.WORKFLOW, "completed")
    assert runtime._load_json(configured["path"])["last_run"]["status"] == "completed"
    assert pilot.run_daily_restic_pilot()["reason"] == "daily-attempt-already-recorded"
    assert configured["create"].call_count == 2
    configured["maintenance"].assert_called_once()
    assert configured["maintenance"].call_args.kwargs == {"dry_run": True}


def test_missing_initial_coverage_marks_full_run_as_seed(configured, monkeypatch):
    monkeypatch.setattr(pilot.backup_store, "list_backups", lambda *, source_id, limit: ([], 0) if source_id == "project" else ([configured["rows"][source_id]], 1))
    result = pilot.run_daily_restic_pilot()
    assert result["seed"] is True
    assert result["missing_seed_sources"] == ["project"]
    assert result["coverage_verified"] is True
    assert result["cutover_qualified"] is False
    assert all(call.kwargs["note"] == "Daily seed Restic pilot" for call in configured["create"].call_args_list)


def test_separately_qualified_prune_is_inside_measured_maintenance(configured):
    configured["backend"]["config"]["restic_offsite_prune_qualified"] = True
    assert pilot.run_daily_restic_pilot()["status"] == "completed"
    assert configured["maintenance"].call_args.kwargs == {"dry_run": False}


def test_before_daily_utc_time_does_not_capture(configured, monkeypatch):
    class BeforeDaily(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 9, 29, 1, tzinfo=UTC)

    monkeypatch.setattr(pilot, "datetime", BeforeDaily)
    monkeypatch.setattr(pilot.settings, "backup_restic_pilot_daily_utc", "02:00")
    assert pilot.run_daily_restic_pilot()["reason"] == "before-daily-utc-time"
    configured["create"].assert_not_called()


def test_crossing_utc_date_cannot_claim_start_day_coverage(configured, monkeypatch):
    start = datetime(2026, 9, 29, 2, tzinfo=UTC)
    readings = iter([start, start, start + timedelta(days=1)])

    class CrossingDate(datetime):
        @classmethod
        def now(cls, tz=None):
            return next(readings)

    monkeypatch.setattr(pilot, "datetime", CrossingDate)
    result = pilot.run_daily_restic_pilot()
    assert result["status"] == "failed"
    assert result["crossed_utc_date"] is True
    assert result["coverage_verified"] is False
    assert result["measurement"]["valid"] is True


def test_overlapping_invocation_never_double_executes(configured):
    root = configured["path"].parent
    root.mkdir(mode=0o700)
    with (root / ".pilot.lock").open("w") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert pilot.run_daily_restic_pilot()["reason"] == "pilot-active"
    configured["create"].assert_not_called()


def test_interrupted_restart_cannot_retry_same_day_to_qualify(configured):
    configured["path"].parent.mkdir(mode=0o700)
    runtime._save_json(configured["path"], {"last_run": {
        "status": "running", "day_utc": datetime.now(UTC).date().isoformat(),
        "started_at": datetime.now(UTC).isoformat(), "samples": [_sample()], "outcomes": [],
    }})
    result = pilot.run_daily_restic_pilot()
    assert result["daily_status"] == "incomplete"
    configured["create"].assert_not_called()
    saved = runtime._load_json(configured["path"])["last_run"]
    assert saved["coverage_verified"] is False
    assert saved["measurement"]["valid"] is False
    assert "interrupted-process-restart" in saved["measurement"]["errors"]
    assert configured["history"].call_args.args == (pilot.WORKFLOW, "incomplete")


@pytest.mark.parametrize("daily", ["24:00", "1:00", "00:60", "daily", ""])
def test_invalid_daily_interval_fails_before_operations(configured, monkeypatch, daily):
    monkeypatch.setattr(pilot.settings, "backup_restic_pilot_daily_utc", daily)
    assert pilot.run_daily_restic_pilot()["status"] == "failed"
    configured["create"].assert_not_called()


@pytest.mark.parametrize("change", [{"is_default": True}, {"enabled": False}, {"config": {"engine": "native"}}])
def test_backend_must_be_explicit_enabled_nondefault_restic(configured, change):
    configured["backend"].update(change)
    assert pilot.run_daily_restic_pilot()["status"] == "failed"
    configured["create"].assert_not_called()


def test_counter_read_failure_is_failed_not_zero(configured, monkeypatch):
    monkeypatch.setattr(pilot, "sample_interface", Mock(side_effect=OSError("interface missing")))
    result = pilot.run_daily_restic_pilot()
    assert result["status"] == "failed"
    assert result["coverage_verified"] is False
    assert "total_bytes" not in result.get("measurement", {})
    configured["create"].assert_not_called()


def test_history_failure_before_capture_fails_closed(configured):
    configured["history"].side_effect = RuntimeError("history unavailable")
    result = pilot.run_daily_restic_pilot()
    assert result["status"] == "failed"
    assert "history_error" in result
    assert runtime._load_json(configured["path"])["last_run"]["status"] == "failed"
    configured["create"].assert_not_called()


def test_final_history_failure_cannot_leave_private_success(configured):
    def record(*args, **kwargs):
        if args[1] == "completed":
            raise RuntimeError("final history unavailable")

    configured["history"].side_effect = record
    assert pilot.run_daily_restic_pilot()["status"] == "failed"
    saved = runtime._load_json(configured["path"])["last_run"]
    assert saved["status"] == "failed"
    assert saved["checkpoint_error"] == "final history unavailable"
    assert pilot.run_daily_restic_pilot()["daily_status"] == "failed"


@pytest.mark.parametrize("changes,error", [
    ({"boot_id": "new-boot"}, "boot-interface-or-route-changed"),
    ({"route_sha256": "new-route"}, "boot-interface-or-route-changed"),
    ({"ifindex": "3"}, "boot-interface-or-route-changed"),
    ({"rx_bytes": 0}, "physical-counter-reset"),
    ({"timestamp": _sample()["timestamp"]}, "invalid-measurement-interval"),
    ({"timestamp": "garbage"}, "invalid-measurement-sample"),
])
def test_changed_identity_or_bad_intervals_invalidate(changes, error):
    samples = [_sample(), {**_sample(1), **changes}]
    result = pilot.measure_samples(samples, [])
    assert result["valid"] is False
    assert error in result["errors"]
    assert "total_bytes" not in result


def test_pending_offsite_gets_bounded_measured_retry_and_fails(configured):
    configured["rows"]["project"]["verification_json"]["offsite"]["status"] = "pending"
    configured["retry"].side_effect = RuntimeError("offsite unavailable")
    result = pilot.run_daily_restic_pilot()
    assert result["status"] == "failed"
    assert result["coverage_verified"] is False
    configured["retry"].assert_called_once_with("project", on_progress=None)
    assert result["outcomes"][0]["attempts"][-1]["status"] == "failed"
    assert len(result["outcomes"]) == 2  # Still attempt every enabled source.
    assert result["measurement"]["valid"] is True  # Failed traffic remains counted.


def test_retry_verifies_current_capture_and_preserves_failed_attempt(configured):
    row = configured["rows"]["project"]
    row["status"] = "completed_pending_upload"
    row["verification_json"]["offsite"]["status"] = "pending"

    def verified(*args, **kwargs):
        row["status"] = "completed"
        row["verification_json"]["offsite"]["status"] = "verified"

    configured["retry"].side_effect = verified
    result = pilot.run_daily_restic_pilot()
    assert result["status"] == "completed"
    assert result["coverage_verified"] is True
    assert result["outcomes"][0]["had_failed_attempt"] is True
    assert configured["create"].call_count == 2


def test_failed_maintenance_cannot_report_daily_success(configured):
    configured["maintenance"].return_value = {"remote": {"monthly": {"verified": False}}}
    result = pilot.run_daily_restic_pilot()
    assert result["status"] == "failed"
    assert result["coverage_verified"] is True
    assert result["measurement"]["valid"] is True


def test_enabled_source_change_invalidates_full_coverage(configured):
    configured["maintenance"].side_effect = lambda *args, **kwargs: configured["sources"].append({"id": "new", "enabled": True}) or {"status": "completed"}
    result = pilot.run_daily_restic_pilot()
    assert result["status"] == "failed"
    assert result["sources_changed"] is True


def test_hourly_maintenance_never_escapes_pilot_window(configured, monkeypatch):
    backends = [configured["backend"], {**configured["backend"], "id": "other"}]
    monkeypatch.setattr(pilot.backup_store, "list_backends", lambda **kwargs: backends)
    maintenance = Mock(return_value={"status": "completed"})
    monkeypatch.setattr(runtime, "maintain_repository", maintenance)
    assert runtime.run_repository_maintenance() == {"other": {"status": "completed"}}
    assert maintenance.call_args.args[0]["BACKUP_STORAGE_BACKEND_ID"] == "other"
    assert maintenance.call_count == 1


def test_missing_explicit_backend_reserves_all_repository_maintenance(configured, monkeypatch):
    monkeypatch.setattr(pilot.settings, "backup_restic_pilot_backend_id", "")
    monkeypatch.setattr(pilot.backup_store, "list_backends", lambda **kwargs: [configured["backend"]])
    maintenance = Mock()
    monkeypatch.setattr(runtime, "maintain_repository", maintenance)
    assert runtime.run_repository_maintenance() == {}
    assert pilot.run_daily_restic_pilot()["status"] == "failed"
    maintenance.assert_not_called()


@pytest.mark.parametrize("physical,default,error", [
    (False, "enp8s0", "physical"), (True, "other", "default route"), (True, "enp8s0", None),
])
def test_physical_counter_sampler_rejects_virtual_or_wrong_route(tmp_path, monkeypatch, physical, default, error):
    net = tmp_path / "sys/class/net/enp8s0"
    (net / "statistics").mkdir(parents=True)
    if physical:
        (net / "device").mkdir()
    for name, value in {"ifindex": "2", "iflink": "2", "address": "fixture"}.items():
        (net / name).write_text(value)
    (net / "statistics/rx_bytes").write_text("123")
    (net / "statistics/tx_bytes").write_text("456")
    (tmp_path / "proc/net").mkdir(parents=True)
    (tmp_path / "proc/net/route").write_text(f"Iface Destination Gateway Flags\n{default} 00000000 01010101 0003\n")
    (tmp_path / "proc/net/ipv6_route").write_text("")
    (tmp_path / "proc/sys/kernel/random").mkdir(parents=True)
    (tmp_path / "proc/sys/kernel/random/boot_id").write_text("fixture-boot")
    monkeypatch.setattr(pilot, "Path", lambda value: tmp_path / str(value).lstrip("/"))
    if error:
        with pytest.raises(ValueError, match=error):
            pilot.sample_interface("enp8s0")
    else:
        sample = pilot.sample_interface("enp8s0")
        assert sample["rx_bytes"] == 123
        assert sample["tx_bytes"] == 456
        assert sample["boot_id"] == "fixture-boot"


def test_scheduler_maintenance_failures_are_truthful(configured, monkeypatch):
    monkeypatch.setattr(pilot.settings, "backup_restic_pilot_enabled", False)
    for name in ("_fail_stale_running_records", "_cleanup_stale_records", "_cleanup_expired_records"):
        monkeypatch.setattr(scheduler, name, lambda: 0)
    monkeypatch.setattr(scheduler, "_cleanup_local_archives", lambda: {})
    monkeypatch.setattr(pilot.backup_store, "list_due_sources", lambda: [])
    monkeypatch.setattr(scheduler, "run_scheduled_drills", lambda: {"status": "skipped"})
    monkeypatch.setattr(runtime, "run_repository_maintenance", lambda: {"other": {"status": "failed"}})
    assert scheduler.run_scheduled_backups()["status"] == "partial"
