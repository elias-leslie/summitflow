"""Repository integration safety with synthetic payloads and isolated adapters."""

from __future__ import annotations

import copy
import inspect
import json
import os
import shutil
import tarfile
from contextlib import contextmanager, nullcontext
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.tasks import backup_repository_runtime as runtime
from app.tasks.backup_restic import ResticAdapter, ResticConfig, ResticError
from app.utils import transient_scratch

SNAPSHOT = "a" * 64
REPOSITORY = "b" * 64
PREVIOUS = "c" * 64
LAST_GOOD = "d" * 64
REMOTE_SNAPSHOT = "e" * 64


@pytest.fixture(autouse=True)
def synthetic_restore_mount(tmp_path, monkeypatch):
    root = tmp_path / "restore-scratch"
    root.mkdir(mode=0o700)
    monkeypatch.setattr(transient_scratch, "SCRATCH_ROOT", root)
    monkeypatch.setattr(Path, "is_mount", lambda path: path == root)
    usage = shutil.disk_usage(tmp_path)
    monkeypatch.setattr(transient_scratch.shutil, "disk_usage", lambda _path: usage._replace(free=100 * 1024**3))


@pytest.fixture
def repository_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Normal repository integration uses the existing admission interfaces;
    # actual restart/maintenance contention is covered with in-memory Redis.
    redis = MagicMock()
    redis.eval.return_value = 1
    monkeypatch.setattr("app.tasks.backup_lock.get_redis", lambda: redis)
    monkeypatch.setattr(runtime, "create_notification", MagicMock(return_value={"id": "notification"}))
    monkeypatch.setenv("SF_HOST_RETENTION_PRESSURE_MIN_FREE_GB", "0")
    keys = tmp_path / "keys"
    keys.mkdir(mode=0o700)
    for filename in ("local-password", "remote-password"):
        (keys / filename).touch(mode=0o600)
    local = tmp_path / "local"
    local.mkdir(mode=0o700)
    remote = tmp_path / "remote"
    remote.mkdir(mode=0o700)
    env = {
        "BACKUP_ENGINE": "restic", "BACKUP_STORAGE_BACKEND_ID": "pilot",
        "RESTIC_LOCAL_REPOSITORY": str(local), "RESTIC_REMOTE_REPOSITORY": str(remote),
        "RESTIC_LOCAL_PASSWORD_FILE": str(keys / "local-password"),
        "RESTIC_REMOTE_PASSWORD_FILE": str(keys / "remote-password"),
        "RESTIC_KEY_DIRECTORY": str(keys), "RESTIC_OFFSITE_PRUNE_QUALIFIED": "true",
    }
    monkeypatch.setattr(runtime, "backup_key_directory", lambda: keys)
    config = ResticConfig.from_env(env)
    adapter = MagicMock(config=config)
    adapter.quota_free_bytes.return_value = 1024**3
    adapter.physical_bytes.return_value = 22

    def payload(_source, _name, staging, _env, **_kwargs):
        snapshot = staging / "payload"
        snapshot.mkdir(mode=0o700)
        (snapshot / "work.txt").write_text("synthetic working copy")
        return {"snapshot_dir": snapshot, "total_files": 1, "db_bytes": 0, "recovery": {}}

    saved = {
        "status": "completed", "snapshot_id": SNAPSHOT, "repository_id": REPOSITORY,
        "location": f"restic-v1:{REPOSITORY}:{SNAPSHOT}", "total_bytes": 22,
        "files_bytes": 22, "db_bytes": 0, "data_added_bytes": 12,
        "verification": {
            "verified": True, "format": "restic-v1", "snapshot_id": SNAPSHOT,
            "repository_id": REPOSITORY, "structural_check_at": datetime.now(UTC).isoformat(),
            "capture": {},
        },
    }
    adapter.save_payload.side_effect = lambda *_args: copy.deepcopy(saved)
    monkeypatch.setattr(runtime, "ResticAdapter", lambda _config: adapter)
    monkeypatch.setattr(runtime, "prepare_project_payload", payload)
    monkeypatch.setattr(runtime, "canonical_backup_source_roots", lambda: {})
    record = MagicMock()
    monkeypatch.setattr(runtime, "record_local_archive", record)
    return env, config, adapter, record


def _durable_state(config: ResticConfig):
    paths = list((config.key_directory / "restic-state").glob("*/state.json"))
    assert len(paths) == 1
    return paths[0].parent, json.loads(paths[0].read_text())


def test_pending_snapshot_is_durable_before_sql_failure_and_plaintext_is_removed(repository_fixture, tmp_path: Path):
    env, config, adapter, record = repository_fixture

    def unavailable(_result):
        _directory, checkpoint = _durable_state(config)
        assert checkpoint["sources"]["source"]["snapshot_id"] == SNAPSHOT
        assert checkpoint["offsite"]["pending_snapshot_ids"] == [SNAPSHOT]
        assert checkpoint["sources"]["source"]["result"]["verification"]["storage_backend_id"] == "pilot"
        raise RuntimeError("SQL checkpoint unavailable")

    record.side_effect = unavailable
    with pytest.raises(RuntimeError, match="SQL checkpoint unavailable"):
        runtime.run_repository_backup(project_dir=str(tmp_path / "source"), source_id="source", env=env)

    directory, checkpoint = _durable_state(config)
    assert checkpoint["offsite"]["pending_snapshot_ids"] == [SNAPSHOT]
    assert not (directory / "payloads").exists()
    captured = Path(adapter.save_payload.call_args.args[1]["snapshot_dir"])
    assert captured.is_relative_to(transient_scratch.SCRATCH_ROOT)
    assert not captured.parent.exists()
    adapter.sync.assert_not_called()


@pytest.mark.parametrize("failure", ["missing-oauth", "failed-copy"])
def test_failed_new_copy_keeps_pending_scope_and_prior_last_good(repository_fixture, tmp_path: Path, failure: str):
    env, config, adapter, record = repository_fixture
    with runtime._checkpoint(config) as (directory, state):
        state["sources"]["source"] = {
            "snapshot_id": PREVIOUS, "baseline_snapshot_id": PREVIOUS,
            "last_good_snapshot_id": LAST_GOOD, "recovery": {},
        }
        state["offsite"] = {"pending_snapshot_ids": [PREVIOUS]}
        runtime._save_json(directory / "state.json", state)

    def failed(snapshot_id, *, state, persist):
        _directory, checkpoint = _durable_state(config)
        assert snapshot_id == SNAPSHOT
        assert checkpoint["offsite"]["pending_snapshot_ids"] == [PREVIOUS, SNAPSHOT]
        assert checkpoint["sources"]["source"]["last_good_snapshot_id"] == LAST_GOOD
        assert state["pending_snapshot_ids"] == [PREVIOUS, SNAPSHOT]
        raise ResticError("OAuth configuration unavailable" if failure == "missing-oauth" else "Copy interrupted")

    adapter.sync.side_effect = failed
    result = runtime.run_repository_backup(project_dir=str(tmp_path / "source"), source_id="source", env=env)

    assert result["status"] == "completed_pending_upload"
    assert result["verification"]["offsite"]["status"] == "pending"
    record.assert_called_once()
    directory, checkpoint = _durable_state(config)
    assert checkpoint["sources"]["source"]["snapshot_id"] == SNAPSHOT
    assert checkpoint["sources"]["source"]["last_good_snapshot_id"] == LAST_GOOD
    assert checkpoint["sources"]["source"]["baseline_snapshot_id"] == PREVIOUS
    assert checkpoint["offsite"]["pending_snapshot_ids"] == [PREVIOUS, SNAPSHOT]
    assert not (directory / "payloads").exists()
    captured = Path(adapter.save_payload.call_args.args[1]["snapshot_dir"])
    assert captured.is_relative_to(transient_scratch.SCRATCH_ROOT)
    assert not captured.parent.exists()


def test_missing_oauth_configuration_keeps_local_completion_and_pending_reference(repository_fixture, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    env, _config, adapter, _record = repository_fixture
    env = {**env, "RESTIC_REMOTE_REPOSITORY": "rclone:fixture:bounded-repository"}
    config = ResticConfig.from_env(env)
    saved = adapter.save_payload("source", {})
    monkeypatch.setattr(runtime, "ResticAdapter", ResticAdapter)
    monkeypatch.setattr(ResticAdapter, "save_payload", lambda *_args: saved)
    command = MagicMock(side_effect=AssertionError("No subprocess may run without OAuth configuration"))
    monkeypatch.setattr(ResticAdapter, "_run", command)

    result = runtime.run_repository_backup(project_dir=str(tmp_path / "source"), source_id="source", env=env)

    assert result["status"] == "completed_pending_upload"
    assert result["verification"]["offsite"]["status"] == "pending"
    assert "RESTIC_RCLONE_CONFIG is required" in result["verification"]["offsite"]["error"]
    _directory, state = _durable_state(config)
    assert state["offsite"]["pending_snapshot_ids"] == [SNAPSHOT]
    assert state["sources"]["source"]["snapshot_id"] == SNAPSHOT
    command.assert_not_called()


@pytest.mark.parametrize("failed_remote", [None, False, True])
def test_failed_monthly_read_skips_forget_and_prune(repository_fixture, monkeypatch: pytest.MonkeyPatch, failed_remote):
    env, config, adapter, _record = repository_fixture
    monkeypatch.setattr(runtime.backup_store, "list_sources", lambda: [{"id": "source", "enabled": True, "retention_days": 14}])
    monkeypatch.setattr(runtime, "_weekly_critical_restore", lambda *_args, **_kwargs: {"status": "skipped"})
    reconcile = MagicMock(return_value=0)
    monkeypatch.setattr(runtime, "_reconcile_catalogue", reconcile)
    adapter.check.side_effect = lambda **kwargs: {
        "verified": failed_remote is not None and kwargs["remote"] != failed_remote,
        "error": "Synthetic checksum mismatch",
        "state": {"next_bucket": 3}, "checked_at": datetime.now(UTC).isoformat(),
    }

    result = runtime.maintain_repository(env, dry_run=False)

    for label in ("local", "remote"):
        expected_verified = failed_remote is not None and (label == "remote") != failed_remote
        assert result[label]["monthly"]["verified"] is expected_verified
        assert result[label]["retention"]["status"] == "skipped"
        assert result[label]["prune"]["status"] == "skipped"
    adapter.retention.assert_not_called()
    adapter.prune.assert_not_called()
    reconcile.assert_not_called()
    _directory, state = _durable_state(config)
    for label in ("local", "remote"):
        expected_verified = failed_remote is not None and (label == "remote") != failed_remote
        assert ("monthly_checked_at" in state["maintenance"][label]) is expected_verified


def test_failed_critical_restore_blocks_both_retention_paths(repository_fixture, monkeypatch: pytest.MonkeyPatch):
    env, config, adapter, _record = repository_fixture
    monkeypatch.setattr(runtime.backup_store, "list_sources", lambda: [{"id": "source", "enabled": True, "retention_days": 14}])
    monkeypatch.setattr(runtime, "_weekly_critical_restore", lambda *_args, **_kwargs: {"status": "failed", "failed_source": "source"})
    monkeypatch.setattr(runtime, "_reconcile_catalogue", MagicMock(side_effect=AssertionError("No catalogue expiry after failed restore")))
    adapter.check.side_effect = lambda **_kwargs: {
        "verified": True, "state": {"next_bucket": 3}, "checked_at": datetime.now(UTC).isoformat(),
    }

    result = runtime.maintain_repository(env, dry_run=False)

    assert result["critical_restore"]["status"] == "failed"
    assert result["local"]["retention"]["status"] == "skipped"
    assert result["remote"]["retention"]["status"] == "skipped"
    adapter.retention.assert_not_called()
    adapter.prune.assert_not_called()
    _directory, state = _durable_state(config)
    assert state["maintenance"]["critical_restore_result"]["status"] == "failed"


def test_interrupted_remote_prune_resumes_before_any_fresh_retention(repository_fixture, monkeypatch: pytest.MonkeyPatch):
    env, config, adapter, _record = repository_fixture
    with runtime._checkpoint(config) as (directory, state):
        state["offsite"] = {"maintenance": {"status": "pending", "operation": "prune", "phase": "prepared"}}
        runtime._save_json(directory / "state.json", state)
    monkeypatch.setattr(runtime.backup_store, "list_sources", lambda: [{"id": "source", "enabled": True, "retention_days": 14}])
    monkeypatch.setattr(runtime, "_weekly_critical_restore", lambda *_args, **_kwargs: {"status": "skipped"})
    monkeypatch.setattr(runtime, "_reconcile_catalogue", lambda *_args: 0)
    adapter.check.side_effect = lambda **_kwargs: {
        "verified": True, "state": {"next_bucket": 3}, "checked_at": datetime.now(UTC).isoformat(),
    }
    adapter.quota_free_bytes.return_value = 4 * 1024**3
    operations = []

    def prune(*, remote, state, persist, **_kwargs):
        operations.append(("prune", remote))
        if state.get("maintenance", {}).get("status") == "pending":
            journal = copy.deepcopy(state)
            journal["maintenance"]["status"] = "completed"
            persist(journal)
            return {"status": "completed", "completed_at": datetime.now(UTC).isoformat()}
        return {"status": "skipped", "reason": "weekly-cadence"}

    def retention(*_args, remote, state, **_kwargs):
        operations.append(("retention", remote))
        assert state.get("maintenance", {}).get("status") != "pending"
        return {"status": "completed", "state": state}

    adapter.prune.side_effect = prune
    adapter.retention.side_effect = retention

    result = runtime.maintain_repository(env, dry_run=False)

    assert operations[0] == ("prune", True)
    assert ("retention", True) in operations
    assert result["resumed_prune"]["status"] == "completed"
    _directory, state = _durable_state(config)
    assert state["offsite"]["maintenance"]["status"] == "completed"


@pytest.fixture
def mapped_archives(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from app.tasks import backup_executor as executor
    from app.tasks import backup_native_recovery as recovery

    skills = tmp_path / "original-skills"
    skills.mkdir()
    (skills / "SKILL.md").write_text("synthetic skill")
    config = tmp_path / "original-config"
    config.mkdir()
    (config / "settings.txt").write_text("synthetic settings")
    (config / "skills").symlink_to(skills)
    archives = {}
    backups = {}
    for source_id, source in (("codex-config", config), ("agent-skills", skills)):
        snapshot, _manifest = recovery.build_consistent_snapshot(
            source, tmp_path / f"stage-{source_id}", (), lambda *_args: False,
            source_roots={"agent-skills": skills},
        )
        archive = tmp_path / f"{source_id}.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            tar.add(snapshot, arcname="payload")
        archives[source_id] = archive
        backups[source_id] = {
            "id": source_id, "source_id": source_id, "storage_backend_id": "pilot",
            "verification_json": {"format": "restic-v1", "snapshot_id": SNAPSHOT, "remote_snapshot_id": REMOTE_SNAPSHOT},
        }

    @contextmanager
    def materialize(backup, *, remote=False):
        assert remote is True
        yield archives[backup["source_id"]]

    monkeypatch.setattr(runtime, "materialize_repository_archive", materialize)
    monkeypatch.setattr(executor.backup_store, "get_backup", lambda backup_id: backups[backup_id])
    monkeypatch.setattr(executor.backup_store, "get_source", lambda source_id: {"id": source_id})
    merge = MagicMock()
    monkeypatch.setattr(executor.backup_store, "merge_backup_verification_json", merge)
    return executor, merge


@pytest.mark.parametrize("restore_targets", [False, True])
def test_mapped_restore_is_pending_without_targets_and_complete_with_restored_siblings(
    mapped_archives, tmp_path: Path, restore_targets: bool,
):
    executor, merge = mapped_archives
    isolated = tmp_path / "isolated"
    roots = None
    if restore_targets:
        target = isolated / "agent-skills"
        target_result = executor.restore_backup_isolated("agent-skills", target, remote=True)
        assert target_result["recovery_complete"] is True
        roots = {"agent-skills": target}

    destination = isolated / "codex-config"
    result = executor.restore_backup_isolated("codex-config", destination, remote=True, destination_roots=roots)

    assert result["recovery_complete"] is restore_targets
    evidence = result["evidence"]
    assert evidence is not None
    assert evidence["recovery_complete"] is restore_targets
    assert (destination / "settings.txt").read_text() == "synthetic settings"
    link = destination / "skills"
    if restore_targets:
        assert roots is not None
        assert result["mapped_links_restored"] == 1
        assert result["mapped_links_pending"] == []
        assert link.resolve() == roots["agent-skills"]
        assert not Path(os.readlink(link)).is_absolute()
        assert (link / "SKILL.md").read_text() == "synthetic skill"
    else:
        assert result["mapped_links_restored"] == 0
        assert len(result["mapped_links_pending"]) == 1
        assert not link.exists() and not link.is_symlink()
    assert merge.call_args.args[1]["isolated_restore"]["recovery_complete"] is restore_targets


def test_mapped_recovery_rejects_restored_targets_outside_sibling_isolation(mapped_archives, tmp_path: Path):
    executor, merge = mapped_archives
    outside = tmp_path / "other-isolation" / "agent-skills"
    executor.restore_backup_isolated("agent-skills", outside, remote=True)
    destination = tmp_path / "isolated" / "codex-config"

    with pytest.raises(RuntimeError, match="restored source siblings"):
        executor.restore_backup_isolated(
            "codex-config", destination, remote=True, destination_roots={"agent-skills": outside},
        )

    assert not (destination / "skills").exists()
    assert not (destination / "skills").is_symlink()
    assert merge.call_args.args[1]["isolated_restore"]["ok"] is False


@pytest.mark.parametrize("fails", [False, True])
def test_idle_scheduler_runs_repository_maintenance_and_records_outcome(monkeypatch: pytest.MonkeyPatch, fails: bool):
    from app.tasks import backup_scheduler as scheduler

    for name in ("_fail_stale_running_records", "_cleanup_stale_records", "_cleanup_expired_records"):
        monkeypatch.setattr(scheduler, name, lambda: 0)
    monkeypatch.setattr(scheduler, "_cleanup_local_archives", lambda: {})
    monkeypatch.setattr(scheduler.backup_store, "list_due_sources", lambda: [])
    monkeypatch.setattr(scheduler, "run_scheduled_drills", lambda: {"status": "skipped"})
    maintenance = MagicMock(return_value={"pilot": {"dry_run": True}})
    if fails:
        maintenance.side_effect = ResticError("Repository maintenance unavailable")
    monkeypatch.setattr(runtime, "run_repository_maintenance", maintenance)
    record = MagicMock()
    monkeypatch.setattr(scheduler.maintenance_store, "record_maintenance_run", record)

    result = scheduler.run_scheduled_backups()

    maintenance.assert_called_once()
    assert result["count"] == 0
    expected = {"status": "error"} if fails else {"pilot": {"dry_run": True}}
    assert result["repository_maintenance"] == expected
    assert record.call_args.kwargs["summary"]["repository_maintenance"] == expected


def _catalogue_row(backup_id, **updates):
    return {
        "id": backup_id, "storage_backend_id": "pilot", "status": "completed",
        "verification_json": {
            "format": "restic-v1", "snapshot_id": SNAPSHOT, "remote_snapshot_id": REMOTE_SNAPSHOT,
            "offsite": {"status": "verified"},
        }, **updates,
    }


def test_catalogue_reconciles_only_points_absent_from_both_repositories(monkeypatch: pytest.MonkeyPatch):
    adapter = MagicMock(config=SimpleNamespace(remote_repository="rclone:fixture:bounded"))
    adapter.snapshots.side_effect = lambda *, remote=False: [{"id": LAST_GOOD}] if remote else [{"id": PREVIOUS}]
    rows = [
        _catalogue_row("gone"),
        _catalogue_row("local-present", verification_json={"format": "restic-v1", "snapshot_id": PREVIOUS, "remote_snapshot_id": REMOTE_SNAPSHOT}),
        _catalogue_row("remote-present", verification_json={"format": "restic-v1", "snapshot_id": SNAPSHOT, "remote_snapshot_id": LAST_GOOD}),
        _catalogue_row("active", verification_json={"format": "restic-v1", "snapshot_id": SNAPSHOT, "remote_snapshot_id": REMOTE_SNAPSHOT, "activity": {"active": True}}),
        _catalogue_row("pending", status="completed_pending_upload"),
        _catalogue_row("running", status="running"),
        _catalogue_row("other-backend", storage_backend_id="other"),
        _catalogue_row("legacy", verification_json={}),
    ]
    pages = []

    def list_rows(*, limit, offset):
        assert limit == 100
        pages.append(offset)
        return rows[offset:offset + 2], len(rows)

    monkeypatch.setattr(runtime.backup_store, "list_backups", list_rows)
    delete = MagicMock(return_value=True)
    monkeypatch.setattr(runtime.backup_store, "delete_backup_record", delete)

    assert runtime._reconcile_catalogue(adapter, {"BACKUP_STORAGE_BACKEND_ID": "pilot"}) == 1
    assert pages == [0, 2, 4, 6]
    delete.assert_called_once_with("gone")


def test_catalogue_expires_local_only_point_after_local_forget_on_dual_repo_backend(monkeypatch: pytest.MonkeyPatch):
    adapter = MagicMock(config=SimpleNamespace(remote_repository="rclone:fixture:bounded"))
    adapter.snapshots.return_value = []
    rows = [
        _catalogue_row("local-only", verification_json={"format": "restic-v1", "snapshot_id": SNAPSHOT, "offsite": {"status": "not_requested"}}),
        _catalogue_row("unknown-remote", verification_json={"format": "restic-v1", "snapshot_id": PREVIOUS, "offsite": {"status": "verified"}}),
    ]
    monkeypatch.setattr(runtime.backup_store, "list_backups", lambda **_kwargs: (rows, len(rows)))
    delete = MagicMock(return_value=True)
    monkeypatch.setattr(runtime.backup_store, "delete_backup_record", delete)

    assert runtime._reconcile_catalogue(adapter, {"BACKUP_STORAGE_BACKEND_ID": "pilot"}) == 1
    delete.assert_called_once_with("local-only")


@pytest.mark.parametrize("remote", [False, True])
def test_unknown_repository_inventory_prevents_sql_reconciliation(monkeypatch: pytest.MonkeyPatch, remote: bool):
    adapter = MagicMock(config=SimpleNamespace(remote_repository="rclone:fixture:bounded"))

    def snapshots(*, remote=False):
        if remote == failure_remote:
            raise ResticError("Repository inventory unavailable")
        return []

    failure_remote = remote
    adapter.snapshots.side_effect = snapshots
    delete = MagicMock()
    monkeypatch.setattr(runtime.backup_store, "delete_backup_record", delete)
    with pytest.raises(ResticError, match="inventory unavailable"):
        runtime._reconcile_catalogue(adapter, {"BACKUP_STORAGE_BACKEND_ID": "pilot"})
    delete.assert_not_called()


@pytest.mark.parametrize("verification", [
    {"format": "restic-v1", "snapshot_id": SNAPSHOT, "remote_snapshot_id": REMOTE_SNAPSHOT, "offsite": {"status": "pending"}},
    {"format": "restic-v1", "snapshot_id": SNAPSHOT, "remote_snapshot_id": REMOTE_SNAPSHOT, "offsite": {"status": "failed"}},
    {"format": "restic-v1", "snapshot_id": SNAPSHOT, "offsite": {"status": "verified"}},
    {"format": "restic-v1"},
])
def test_catalogue_preserves_pending_verification_or_unproven_snapshot_refs(monkeypatch: pytest.MonkeyPatch, verification):
    adapter = MagicMock(config=SimpleNamespace(remote_repository="rclone:fixture:bounded"))
    adapter.snapshots.return_value = []
    monkeypatch.setattr(runtime.backup_store, "list_backups", lambda **_kwargs: ([_catalogue_row("protected", verification_json=verification)], 1))
    delete = MagicMock(return_value=True)
    monkeypatch.setattr(runtime.backup_store, "delete_backup_record", delete)

    assert runtime._reconcile_catalogue(adapter, {"BACKUP_STORAGE_BACKEND_ID": "pilot"}) == 0
    delete.assert_not_called()


@pytest.mark.parametrize("ok", [False, True])
def test_infrastructure_drill_uses_repository_materialization_and_records_actual_result(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, ok: bool):
    from app.tasks import backup_restore_drill as drill

    backup = _catalogue_row("infrastructure-point", source_id="infrastructure")
    archive = tmp_path / "materialized-infrastructure.tar.gz"
    archive.touch()
    monkeypatch.setattr(drill, "_find_infra_source", lambda: {"id": "infrastructure"})
    monkeypatch.setattr(drill.backup_store, "get_latest_backup", lambda **_kwargs: backup)
    materialize = MagicMock(return_value=nullcontext(archive))
    monkeypatch.setattr(runtime, "materialize_repository_archive", materialize)
    run = MagicMock(return_value={"ok": ok, "components": [], "backup_id": backup["id"]})
    monkeypatch.setattr(drill, "_run_drill_script", run)
    record = MagicMock()
    monkeypatch.setattr(drill, "_record_drill_result", record)
    legacy = MagicMock(side_effect=AssertionError("Repository drill must not use archive/SMB lookup"))
    monkeypatch.setattr(drill, "_locate_drill_archive", legacy)

    result = drill.run_infra_drill()

    assert result["ok"] is ok
    materialize.assert_called_once_with(backup)
    run.assert_called_once_with(str(archive), "infrastructure-point")
    assert record.call_args.kwargs["ok"] is ok
    legacy.assert_not_called()


@pytest.mark.parametrize("config,delegated", [
    ({"engine": "restic", "restic_remote_repository": "rclone:fixture:bounded", "__backend_id": "pilot"}, True),
    ({"engine": "restic"}, False),
    ({"engine": "native"}, False),
    (None, False),
])
def test_scheduled_drill_delegates_only_remote_repository_recovery(monkeypatch: pytest.MonkeyPatch, config, delegated: bool):
    from app.tasks import backup_restore_drill as drill
    from app.tasks import backup_scheduler as scheduler
    from app.tasks import backup_utils

    monkeypatch.setattr(scheduler.backup_store, "list_sources", lambda: [{"id": "infrastructure", "enabled": True, "source_type": "infrastructure"}])
    resolve = MagicMock(return_value=config)
    monkeypatch.setattr(backup_utils, "get_storage_config", resolve)
    run = MagicMock(return_value={"ok": True})
    monkeypatch.setattr(drill, "run_infra_drill", run)

    result = scheduler.run_scheduled_drills()

    if delegated:
        assert result == {"status": "skipped", "reason": "repository-managed-weekly-offsite-drill", "backend_id": "pilot"}
        run.assert_not_called()
    else:
        assert result["status"] == "completed"
        run.assert_called_once()
    resolve.assert_called_once_with("infrastructure")


@pytest.mark.parametrize("ok", [False, True])
def test_weekly_offsite_drill_records_actual_database_result(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, ok: bool):
    from app.tasks import backup_restore_drill as drill

    backup = _catalogue_row("offsite-infrastructure-point", source_id="infrastructure")
    archive = tmp_path / "offsite.tar.gz"
    archive.touch()
    monkeypatch.setattr(runtime.backup_store, "list_sources", lambda: [{"id": "infrastructure", "enabled": True}])
    monkeypatch.setattr(runtime.backup_store, "list_backups", lambda **_: ([backup], 1))
    materialize = MagicMock(return_value=nullcontext(archive))
    monkeypatch.setattr(runtime, "materialize_repository_archive", materialize)
    actual = {"ok": ok, "components": [{"name": "postgres", "ok": ok}], "backup_id": backup["id"]}
    monkeypatch.setattr(drill, "_run_drill_script", MagicMock(return_value=actual))
    record = MagicMock()
    monkeypatch.setattr(drill, "_record_drill_result", record)
    maintenance = {}

    result = runtime._weekly_critical_restore({"BACKUP_STORAGE_BACKEND_ID": "pilot"}, maintenance)

    assert result["status"] == ("verified" if ok else "failed")
    materialize.assert_called_once_with(backup, remote=True)
    record.assert_called_once_with("infrastructure", backup["id"], ok=ok, result=actual)
    assert ("critical_restore_at" in maintenance) is ok


def test_weekly_critical_restore_does_not_redownload_conversation_trees(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    from app.tasks import backup_executor, backup_native_restore

    canonical = {"codex-config", "claude-config", "agent-skills", "claude-user-config"}
    enabled = canonical | {".codex", ".claude"}
    monkeypatch.setattr(runtime.backup_store, "list_sources", lambda: [{"id": source, "enabled": True} for source in enabled])
    requested = []

    def points(*, source_id, limit):
        requested.append(source_id)
        return [_catalogue_row("point-" + source_id, source_id=source_id)], 1

    monkeypatch.setattr(runtime.backup_store, "list_backups", points)
    monkeypatch.setattr(runtime, "materialize_repository_archive", lambda *_args, **_kwargs: nullcontext(tmp_path / "archive.tar.gz"))
    monkeypatch.setattr(backup_native_restore, "restore_isolated_archive", lambda *_args: {})
    monkeypatch.setattr(backup_executor, "_complete_mapped_recovery", lambda *_args: {"recovery_complete": True})

    result = runtime._weekly_critical_restore({"BACKUP_STORAGE_BACKEND_ID": "pilot"}, {})

    assert result["status"] == "verified"
    assert set(requested) == canonical
    assert set(result["sources"]) == canonical


@pytest.mark.parametrize("failure_stage", ["restore", "database"])
def test_weekly_offsite_drill_records_preverification_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, failure_stage: str):
    from app.tasks import backup_restore_drill as drill

    backup = _catalogue_row("failed-offsite-point", source_id="infrastructure")
    monkeypatch.setattr(runtime.backup_store, "list_sources", lambda: [{"id": "infrastructure", "enabled": True}])
    monkeypatch.setattr(runtime.backup_store, "list_backups", lambda **_: ([backup], 1))
    failure = ResticError("isolated recovery failed")
    materialize = MagicMock(side_effect=failure) if failure_stage == "restore" else MagicMock(return_value=nullcontext(tmp_path / "archive.tar.gz"))
    monkeypatch.setattr(runtime, "materialize_repository_archive", materialize)
    monkeypatch.setattr(drill, "_run_drill_script", MagicMock(side_effect=failure))
    record = MagicMock()
    monkeypatch.setattr(drill, "_record_drill_result", record)
    maintenance = {}

    result = runtime._weekly_critical_restore({"BACKUP_STORAGE_BACKEND_ID": "pilot"}, maintenance)

    assert result["status"] == "failed"
    record.assert_called_once_with("infrastructure", backup["id"], ok=False, error="isolated recovery failed")
    assert "critical_restore_at" not in maintenance


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint,source_type", [("project", "project"), ("source", "project"), ("source", "infrastructure")])
async def test_selected_backend_flows_from_api_workflow_to_project_and_infrastructure_record(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, endpoint: str, source_type: str,
):
    from fastapi import BackgroundTasks

    from app.api.backups import project_endpoints, source_endpoints
    from app.api.backups.models import BackupCreate
    from app.tasks import backup_executor as executor
    from app.tasks import backup_infra as infrastructure
    from app.tasks import backup_utils
    from app.workflows import utility

    source_id = "infrastructure" if source_type == "infrastructure" else "project"
    source_path = tmp_path / "source"
    source_path.mkdir()
    env = {"BACKUP_ENGINE": "restic", "BACKUP_STORAGE_BACKEND_ID": "pilot"}
    monkeypatch.setattr(backup_utils, "get_source_type", lambda _: source_type)
    monkeypatch.setattr(executor, "get_source_path", lambda _: str(source_path))
    monkeypatch.setattr(executor, "get_project_root", lambda _: str(source_path))
    build_env = MagicMock(return_value=env)
    for module in (executor, infrastructure):
        monkeypatch.setattr(module, "build_storage_env", build_env)
        monkeypatch.setattr(module, "acquire_backup_lock", lambda _: "fixture-lease")
        monkeypatch.setattr(module, "maintain_backup_lock", lambda *_args: nullcontext())
        monkeypatch.setattr(module, "bind_backup_activity", lambda *_args: nullcontext())
    monkeypatch.setattr(executor.backup_store, "get_source", lambda _: {"id": source_id, "project_id": source_id})
    monkeypatch.setattr(executor.backup_store, "get_backup", lambda _: None)
    record = MagicMock(return_value={"id": "created-point"})
    status = MagicMock()
    monkeypatch.setattr(executor.backup_store, "create_backup_record", record)
    monkeypatch.setattr(executor.backup_store, "update_backup_status", status)
    capture = MagicMock(return_value={
        "status": "completed", "location": f"restic-v1:{REPOSITORY}:{SNAPSHOT}",
        "total_bytes": 22, "db_bytes": 0, "files_bytes": 22,
        "verification": {"verified": True, "format": "restic-v1", "snapshot_id": SNAPSHOT,
                         "repository_id": REPOSITORY, "storage_backend_id": "pilot", "offsite": {"status": "verified"}},
    })
    monkeypatch.setattr(runtime, "run_repository_backup", capture)
    monkeypatch.setattr(utility, "make_backup_progress_callback", lambda _ctx: None)

    async def inline(function, *args, **kwargs):
        value = function(*args, **kwargs)
        return await value if inspect.isawaitable(value) else value

    monkeypatch.setattr(utility.asyncio, "to_thread", inline)
    workflow_function = utility.backup_create_wf._task.fn
    queued_inputs = []
    completed = []

    class Workflow:
        async def aio_run_no_wait(self, backup_input):
            queued_inputs.append(backup_input)
            value = workflow_function(backup_input, SimpleNamespace())
            completed.append(await value if inspect.isawaitable(value) else value)
            return SimpleNamespace(workflow_run_id="fixture-workflow")

    monkeypatch.setattr(utility, "backup_create_wf", Workflow())
    request = BackupCreate(storage_backend_id="pilot")
    if endpoint == "project":
        result = await project_endpoints.create_project_backup(source_id, request, BackgroundTasks())
    else:
        result = await source_endpoints.create_source_backup(source_id, request)

    assert result.task_id == "fixture-workflow"
    assert queued_inputs[0].storage_backend_id == "pilot"
    assert queued_inputs[0].source_id == source_id
    assert completed[0]["status"] == "completed"
    build_env.assert_called_once_with(source_id, "pilot")
    assert record.call_args.kwargs["storage_backend_id"] == "pilot"
    assert record.call_args.kwargs["source_id"] == source_id
    assert capture.call_args.kwargs["env"] == env
    assert bool(capture.call_args.kwargs.get("infrastructure")) is (source_type == "infrastructure")
    assert status.call_args.kwargs["verification_json"]["storage_backend_id"] == "pilot"
