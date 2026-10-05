"""Four-hour scheduling and recovery state use the existing serial lifecycle."""

import fcntl
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, Mock

import pytest

from app.api.backups.models import BackupSourceUpdate
from app.api.projects.models import ProjectOnboardingRequest
from app.tasks import backup_repository_runtime as runtime
from app.tasks import backup_scheduler as scheduler
from app.tasks.backup_restic import ResticConfig
from app.tasks.backup_utils import _FREQUENCY_DELTAS, calculate_next_run


def test_four_hourly_frequency_and_daytime_serial_batch(monkeypatch):
    start = datetime.now(UTC)
    assert _FREQUENCY_DELTAS["four_hourly"].total_seconds() == 14400
    assert 14400 <= (calculate_next_run("four_hourly") - start).total_seconds() < 14401
    sources = [{"id": str(i), "frequency": "four_hourly", "next_run_at": start.isoformat()} for i in range(34)]
    sources.append({"id": "night-only", "frequency": "daily", "next_run_at": start.isoformat()})
    monkeypatch.setattr(scheduler, "_scheduled_backup_window_open", lambda _: False)
    monkeypatch.setattr(scheduler, "_scheduled_host_backup", lambda _: {"status": "skipped", "reason": "host-backup-disabled"})
    monkeypatch.setattr(scheduler, "_latest_finished_window_end", lambda _: start)
    monkeypatch.setattr(scheduler.backup_store, "list_due_sources", lambda: sources)
    monkeypatch.setattr(scheduler, "_fail_stale_running_records", lambda: 0)
    monkeypatch.setattr(scheduler.maintenance_store, "record_maintenance_run", lambda *_, **__: None)
    advanced = []
    monkeypatch.setattr(scheduler.backup_store, "update_source_last_run", lambda source_id, next_run: advanced.append((source_id, next_run)))
    order = []
    def capture(**kwargs):
        assert runtime._capture_batch.get() is not None
        order.append(kwargs["source_id"])
        return {"status": "completed_pending_upload"}
    monkeypatch.setattr(scheduler, "create_backup", capture)
    def sync(batch):
        assert runtime._capture_batch.get() is None
        order.append("copy")
        return {}
    monkeypatch.setattr(runtime, "sync_repository_batch", sync)
    for name in ("_cleanup_stale_records", "_cleanup_expired_records", "_cleanup_local_archives", "run_scheduled_drills"):
        monkeypatch.setattr(scheduler, name, Mock(side_effect=AssertionError("daytime maintenance")))
    result = scheduler.run_scheduled_backups()
    assert result["count"] == 34
    assert order == [str(i) for i in range(34)] + ["copy"]
    assert len(advanced) == 34
    assert all(14399 < (due - start).total_seconds() < 14401 for _, due in advanced)


def test_four_hourly_api_and_storage_recalculate_persisted_due(monkeypatch):
    from app.storage.backups import sources

    assert BackupSourceUpdate(frequency="four_hourly").frequency == "four_hourly"
    assert ProjectOnboardingRequest(backup_frequency="four_hourly").backup_frequency == "four_hourly"
    connection = MagicMock()
    cursor = connection.__enter__.return_value.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = None
    monkeypatch.setattr(sources, "get_connection", lambda: connection)
    sources.update_source("fixture", frequency="four_hourly")
    sql, params = cursor.execute.call_args.args
    assert "next_run_at = last_run_at + %s::interval" in str(sql)
    assert params[1].total_seconds() == 14400


def test_payload_fingerprint_reads_bytes_modes_and_recovery_state(tmp_path):
    root = tmp_path / "payload"
    root.mkdir()
    work = root / "work.txt"
    work.write_text("before")
    recovery = root / ".summitflow-recovery"
    recovery.mkdir()
    index = recovery / "index"
    index.write_bytes(b"staged-before")
    payload = {"snapshot_dir": root}
    first = runtime._payload_fingerprint(payload)
    # Same-size saved edits are detected without depending on stat timestamps.
    work.write_text("edited")
    second = runtime._payload_fingerprint(payload)
    assert second != first
    index.write_bytes(b"staged-after!")
    third = runtime._payload_fingerprint(payload)
    assert third != second
    work.chmod(0o700)
    assert runtime._payload_fingerprint(payload) != third


def test_capacity_uses_measured_staging_and_growth_on_shared_filesystem(tmp_path, monkeypatch):
    config = ResticConfig(tmp_path / "repository", tmp_path / "password", tmp_path)
    monkeypatch.setenv("SF_HOST_RETENTION_PRESSURE_MIN_FREE_GB", "0")
    monkeypatch.setattr(runtime.shutil, "disk_usage", lambda _: SimpleNamespace(total=1000, used=850, free=150))
    state = {"sources": {"source": {"capacity": {"staging_peak_bytes": 100, "growth_peak_bytes": 40}}}}
    result = runtime._capacity_admission(config, state, "source")
    assert result["admitted"]
    assert result["filesystems"][0]["required_bytes"] == 140
    assert result["filesystems"][0]["under_pressure"]
    monkeypatch.setattr(runtime.shutil, "disk_usage", lambda _: SimpleNamespace(total=1000, used=870, free=130))
    assert not runtime._capacity_admission(config, state, "source")["admitted"]


def test_copy_capacity_blocks_unknown_quota_and_keeps_backlog(monkeypatch):
    monkeypatch.setenv("SF_HOST_RETENTION_PRESSURE_MIN_FREE_GB", "0")
    adapter = Mock()
    adapter.physical_bytes.return_value = 200
    adapter.quota_free_bytes.return_value = None
    state = {"offsite": {"pending_snapshot_ids": ["a" * 64]}, "sources": {}}
    result = runtime._sync(adapter, Path("/unused"), state, "a" * 64)
    assert result["status"] == "pending"
    assert state["offsite"]["pending_snapshot_ids"] == ["a" * 64]
    adapter.sync.assert_not_called()


def test_reconcile_all_pending_rows_and_latest_checkpoint(monkeypatch):
    local, remote = "b" * 64, "c" * 64
    first, second = "1" * 64, "2" * 64
    state = {"offsite": {"local_repository_id": local, "remote_repository_id": remote, "remote_snapshots": {first: "3" * 64, second: "4" * 64}}, "sources": {"source": {"snapshot_id": second, "last_good_snapshot_id": first, "result": {"pending_path": "restic:pending", "verification": {}}}}}
    rows = [{"id": f"row-{i}", "status": "completed_pending_upload", "verification_json": {"repository_id": local, "snapshot_id": snapshot}} for i, snapshot in enumerate((first, second))]
    monkeypatch.setattr(runtime, "_repository_rows", lambda _: rows)
    merged = Mock()
    status = Mock()
    monkeypatch.setattr(runtime.backup_store, "merge_backup_verification_json", merged)
    monkeypatch.setattr(runtime.backup_store, "update_backup_status", status)
    runtime._reconcile_offsite(state, {"verification": {"offsite": {"status": "verified"}}}, {"BACKUP_STORAGE_BACKEND_ID": "fixture"})
    assert merged.call_count == status.call_count == 2
    assert state["sources"]["source"]["last_good_snapshot_id"] == second
    assert "pending_path" not in state["sources"]["source"]["result"]


def test_host_backup_runs_once_without_due_sources_outside_window(monkeypatch):
    host = Mock(return_value={"status": "completed", "result": "captured"})
    monkeypatch.setattr(scheduler, "_scheduled_host_backup", host)
    monkeypatch.setattr(scheduler, "_scheduled_backup_window_open", lambda _: False)
    monkeypatch.setattr(scheduler, "_latest_finished_window_end", lambda now: now)
    monkeypatch.setattr(scheduler.backup_store, "list_due_sources", lambda: [])
    sync = Mock(return_value={})
    monkeypatch.setattr(runtime, "sync_repository_batch", sync)
    result = scheduler.run_scheduled_backups()
    assert host.call_count == 1
    sync.assert_called_once_with({})
    assert result["host_backup"] == {"status": "completed", "result": "captured"}


@pytest.mark.parametrize("status", ["blocked", "failed", "error", "partial", "cancelled"])
@pytest.mark.parametrize("due", [False, True])
def test_host_backup_failure_is_reported_without_stopping_portable_capture(monkeypatch, status, due):
    host = Mock(return_value={"status": status, "error": "unqualified config"})
    monkeypatch.setattr(scheduler, "_scheduled_host_backup", host)
    monkeypatch.setattr(scheduler, "_scheduled_backup_window_open", lambda _: False)
    monkeypatch.setattr(scheduler, "_latest_finished_window_end", lambda now: now)
    monkeypatch.setattr(scheduler.backup_store, "list_due_sources", lambda: [{"id": "source", "frequency": "four_hourly"}] if due else [])
    monkeypatch.setattr(scheduler, "_fail_stale_running_records", lambda: 0)
    capture = Mock(return_value={"status": "completed"})
    monkeypatch.setattr(scheduler, "create_backup", capture)
    monkeypatch.setattr(scheduler.backup_store, "update_source_last_run", Mock())
    monkeypatch.setattr(scheduler.maintenance_store, "record_maintenance_run", Mock())
    monkeypatch.setattr(runtime, "sync_repository_batch", lambda _: {})
    result = scheduler.run_scheduled_backups()
    assert host.call_count == 1
    assert capture.call_count == int(due)
    assert result["host_backup"]["error"] == "unqualified config"
    assert result["status"] == "partial"


@pytest.mark.parametrize("outcome", ["verified", "pending", "pressure"])
def test_daytime_zero_due_retries_34_persisted_points_once_per_backend(tmp_path, monkeypatch, outcome):
    from app.tasks import backup_restic_pilot
    from app.tasks.backup_utils import storage_config_env

    keys = tmp_path / "keys"
    keys.mkdir(mode=0o700)
    password = keys / "password"
    password.write_text("fixture-only")
    password.chmod(0o600)
    monkeypatch.setattr(runtime, "backup_key_directory", lambda: keys)
    monkeypatch.setenv("SF_HOST_RETENTION_PRESSURE_MIN_FREE_GB", "0")
    backends: list[dict[str, Any]] = [{"id": str(i), "backend_type": "local", "config": {
        "engine": "restic", "restic_local_repository": str(tmp_path / f"local-{i}"),
        "restic_remote_repository": str(tmp_path / f"remote-{i}"),
        "restic_local_password_file": str(password), "restic_key_directory": str(keys),
    }} for i in range(2)]
    rows: dict[str, list[dict[str, Any]]] = {str(i): [{"id": f"row-{j}", "status": "completed_pending_upload", "verification_json": {
        "repository_id": str(i + 1) * 64, "snapshot_id": f"{j + 1:064x}",
        "stored_bytes": 10, "offsite": {"status": "pending"},
    }} for j in range(i * 17, (i + 1) * 17)] for i in range(2)}
    configs = [ResticConfig.from_env(storage_config_env({**item["config"], "__backend_id": item["id"], "__backend_type": "local"})) for item in backends]
    for i, config in enumerate(configs):
        with runtime._checkpoint(config) as (directory, state):
            snapshot = rows[str(i)][0]["verification_json"]["snapshot_id"]
            state.update(offsite={"pinned_snapshot_ids": [snapshot]}, sources={str(i): {
                "snapshot_id": snapshot, "last_good_snapshot_id": "f" * 64,
                "result": {"pending_path": "restic:pending", "verification": {"offsite": {"status": "pending"}}},
            }})
            runtime._save_json(directory / "state.json", state)
    monkeypatch.setattr(scheduler, "_scheduled_host_backup", lambda _: {"status": "skipped"})
    monkeypatch.setattr(scheduler, "_scheduled_backup_window_open", lambda _: False)
    monkeypatch.setattr(scheduler, "_latest_finished_window_end", lambda now: now)
    monkeypatch.setattr(scheduler.backup_store, "list_due_sources", lambda: [])
    monkeypatch.setattr(runtime.backup_store, "list_backends", lambda **_: backends)
    monkeypatch.setattr(backup_restic_pilot, "pilot_reserves_backend", lambda _: False)
    monkeypatch.setattr(runtime, "_repository_rows", lambda env: rows[env["BACKUP_STORAGE_BACKEND_ID"]])
    merged, statuses = Mock(), Mock()
    monkeypatch.setattr(runtime.backup_store, "merge_backup_verification_json", merged)
    monkeypatch.setattr(runtime.backup_store, "update_backup_status", statuses)
    for name in ("create_backup", "_fail_stale_running_records", "_cleanup_stale_records", "_cleanup_expired_records", "_cleanup_local_archives", "run_scheduled_drills"):
        monkeypatch.setattr(scheduler, name, Mock(side_effect=AssertionError("daytime capture or maintenance")))
    monkeypatch.setattr(scheduler.maintenance_store, "record_maintenance_run", Mock(side_effect=AssertionError("capture bookkeeping")))
    adapters = []
    def adapter_factory(config):
        i = configs.index(config)
        adapter = Mock()
        adapter.repository_identity.return_value = {"id": str(i + 1) * 64}
        adapter.physical_bytes.return_value = 170
        adapter.quota_free_bytes.return_value = None if outcome == "pressure" else 1000000
        def sync(snapshot_id, *, state, persist):
            expected = [row["verification_json"]["snapshot_id"] for row in rows[str(i)]]
            assert state["pending_snapshot_ids"] == expected
            assert snapshot_id == expected[-1]
            # A second opener cannot acquire the checkpoint lock during copy.
            with (keys / "restic-state" / runtime._repository_pair(config) / ".state.lock").open("rb") as lock, pytest.raises(BlockingIOError):
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            if outcome == "pending":
                return {"status": "pending", "error": "fixture copy interruption"}
            state.update(local_repository_id=str(i + 1) * 64, remote_repository_id=str(i + 3) * 64,
                         remote_snapshots={item: item for item in expected}, pending_snapshot_ids=[])
            persist(state)
            return {"status": "verified", "verification": {"offsite": {"status": "verified"}}}
        adapter.sync.side_effect = sync
        adapters.append(adapter)
        return adapter
    monkeypatch.setattr(runtime, "ResticAdapter", adapter_factory)
    result = scheduler.run_scheduled_backups()
    assert result["count"] == 0
    assert result["status"] == ("success" if outcome == "verified" else "partial")
    assert len(result["repository_copy"]) == len(adapters) == 2
    assert [adapter.sync.call_count for adapter in adapters] == [int(outcome != "pressure")] * 2
    assert statuses.call_count == merged.call_count == (34 if outcome == "verified" else 0)
    for i, config in enumerate(configs):
        with runtime._checkpoint(config) as (_, state):
            expected = [row["verification_json"]["snapshot_id"] for row in rows[str(i)]]
            assert state["offsite"]["pending_snapshot_ids"] == ([] if outcome == "verified" else expected)
            assert state["offsite"]["pinned_snapshot_ids"] == [expected[0]]
            assert state["sources"][str(i)]["last_good_snapshot_id"] == (expected[0] if outcome == "verified" else "f" * 64)


@pytest.mark.parametrize("engine", ["native", "restic"])
def test_executor_supplies_canonical_project_id_to_actual_engine_dispatch(tmp_path, monkeypatch, engine):
    from app.tasks import backup_executor as executor
    from app.tasks import backup_native as native

    project = tmp_path / "physical-directory-name"
    project.mkdir()
    monkeypatch.setattr(executor, "maintain_backup_lock", lambda *_: nullcontext())
    monkeypatch.setattr(executor, "bind_backup_activity", lambda *_: nullcontext())
    monkeypatch.setattr(executor, "build_storage_env", lambda *_: {"BACKUP_ENGINE": engine, "BACKUP_PROJECT_ID": "wrong-storage-alias"})
    monkeypatch.setattr(executor.backup_store, "create_backup_record", lambda **_: {"id": "record"})
    monkeypatch.setattr(executor.backup_store, "update_backup_status", Mock())
    monkeypatch.setattr(executor.backup_store, "get_backup", lambda _: {})
    received = []
    def restic_capture(**kwargs):
        received.append((kwargs["source_id"], kwargs["env"]["BACKUP_PROJECT_ID"]))
        return {"verification": {"verified": True}, "location": "restic:fixture"}
    monkeypatch.setattr(runtime, "run_repository_backup", restic_capture)
    def native_capture(project_path, project_name, directory, env, **_):
        received.append((project_name, env["BACKUP_PROJECT_ID"]))
        archive = directory / "fixture.tar.gz"
        archive.write_bytes(b"fixture")
        return {"verification": {"verified": True}, "archive_path": archive, "archive_name": archive.name, "total_bytes": 7}
    monkeypatch.setattr(native, "_create_project_archive", native_capture)
    monkeypatch.setattr(native, "canonical_backup_source_roots", lambda: {})
    monkeypatch.setattr(native, "encrypt_completed_archive", lambda *_: {"content_checksum": "fixture", "checksum": "encrypted-fixture", "encrypted_bytes": 7})
    monkeypatch.setattr(native, "_store_local_project_archive", lambda _path, _source, result, *_: {**result, "location": "fixture"})
    result = executor._run_backup("registered-project-alias", str(project), None, "full", False, True,
                                  source_id="source-alias", owner_token="fixture-owner")
    assert result["status"] == "completed"
    assert received == [("source-alias" if engine == "restic" else "physical-directory-name", "registered-project-alias")]
