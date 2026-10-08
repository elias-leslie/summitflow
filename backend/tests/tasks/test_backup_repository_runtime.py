"""Integration regressions using bounded synthetic repositories, never Drive."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import tarfile
from contextlib import contextmanager, nullcontext
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.tasks import backup_repository_runtime as runtime
from app.tasks.backup_restic import ResticAdapter, ResticConfig, ResticError
from app.utils import transient_scratch


@pytest.fixture(autouse=True)
def synthetic_restore_mount(tmp_path, monkeypatch):
    root = tmp_path / "restore-scratch"
    root.mkdir(mode=0o700)
    monkeypatch.setattr(transient_scratch, "SCRATCH_ROOT", root)
    monkeypatch.setattr(Path, "is_mount", lambda path: path == root)
    usage = shutil.disk_usage(tmp_path)
    monkeypatch.setattr(transient_scratch.shutil, "disk_usage", lambda _path: usage._replace(free=100 * 1024**3))


class _MemoryBackupRedis:
    """Exercise the existing admission Lua interfaces without external Redis."""

    def __init__(self):
        self.values = {}

    def set(self, key, value, *, nx=False, ex=None):
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    def get(self, key):
        return self.values.get(key)

    def scan_iter(self, *, match):
        return [key for key in self.values if key.startswith(match.removesuffix("*"))]

    def eval(self, script, count, *args):
        if count == 2:
            key, barrier, owner, _ttl = args
            if barrier in self.values:
                return 0
            return int(self.set(key, owner, nx=True))
        key, owner = args[:2]
        if self.values.get(key) != owner:
            return 0
        if "redis.call('del'" in script:
            del self.values[key]
        return 1


def test_active_repository_maintenance_refuses_restart_and_releases_on_error(repository_env, monkeypatch):
    from app.tasks import backup_lock

    redis = _MemoryBackupRedis()
    monkeypatch.setattr(backup_lock, "get_redis", lambda: redis)
    config = ResticConfig.from_env(repository_env)
    expected = "__repository_maintenance__:" + runtime._repository_pair(config)

    @contextmanager
    def checkpoint(_config):
        with pytest.raises(backup_lock.BackupLockLeaseError, match="Backups active: " + expected), backup_lock.backup_worker_restart_guard():
            pytest.fail("active repository maintenance must refuse restart")
        assert set(redis.values) == {backup_lock.BACKUP_LOCK_PREFIX + expected}
        raise ValueError("synthetic operation failure")
        yield  # pragma: no cover

    monkeypatch.setattr(runtime, "_checkpoint", checkpoint)
    with pytest.raises(ValueError, match="synthetic operation failure"):
        runtime.maintain_repository(repository_env)
    assert redis.values == {}


def test_reserved_restart_refuses_new_repository_maintenance(repository_env, monkeypatch):
    from app.tasks import backup_lock

    redis = _MemoryBackupRedis()
    monkeypatch.setattr(backup_lock, "get_redis", lambda: redis)
    checkpoint = MagicMock(side_effect=AssertionError("no repository work may start"))
    monkeypatch.setattr(runtime, "_checkpoint", checkpoint)
    with backup_lock.backup_worker_restart_guard(), pytest.raises(ResticError, match="maintenance admission"):
        runtime.maintain_repository(repository_env, dry_run=False, force_critical_restore=True)
    checkpoint.assert_not_called()
    assert redis.values == {}


def test_restart_barrier_also_blocks_batch_offsite_sync(repository_env, monkeypatch):
    from app.tasks import backup_lock

    redis = _MemoryBackupRedis()
    monkeypatch.setattr(backup_lock, "get_redis", lambda: redis)
    checkpoint = MagicMock(side_effect=AssertionError("batch repository work must not start"))
    monkeypatch.setattr(runtime, "_checkpoint", checkpoint)
    pair = runtime._repository_pair(ResticConfig.from_env(repository_env))
    with backup_lock.backup_worker_restart_guard():
        result = runtime.sync_repository_batch({pair: repository_env})
    assert result[pair]["status"] == "pending"
    checkpoint.assert_not_called()
    assert redis.values == {}


def test_batch_sync_holds_pair_restart_admission_and_releases_on_error(repository_env, monkeypatch):
    from app.tasks import backup_lock

    redis = _MemoryBackupRedis()
    monkeypatch.setattr(backup_lock, "get_redis", lambda: redis)
    pair = runtime._repository_pair(ResticConfig.from_env(repository_env))

    @contextmanager
    def checkpoint(_config):
        with pytest.raises(backup_lock.BackupLockLeaseError, match="Backups active"), backup_lock.backup_worker_restart_guard():
            pytest.fail("batch sync must block managed restart")
        raise ResticError("synthetic batch failure")
        yield  # pragma: no cover

    monkeypatch.setattr(runtime, "_checkpoint", checkpoint)
    assert runtime.sync_repository_batch({pair: repository_env})[pair]["status"] == "pending"
    assert redis.values == {}


def test_batch_structural_check_and_copy_hold_restart_admission(repository_env, monkeypatch):
    from app.tasks import backup_lock

    redis = _MemoryBackupRedis()
    monkeypatch.setattr(backup_lock, "get_redis", lambda: redis)
    config = ResticConfig.from_env(repository_env)
    pair = runtime._repository_pair(config)
    snapshot = "a" * 64
    adapter = MagicMock()
    adapter.repository_identity.return_value = {"id": "b" * 64}

    def held():
        assert set(redis.values) == {backup_lock.BACKUP_LOCK_PREFIX + "__repository_maintenance__:" + pair}
        with pytest.raises(backup_lock.BackupLockLeaseError), backup_lock.backup_worker_restart_guard():
            pytest.fail("active batch work must block restart")

    def check():
        held()
        return {"verified": True, "checked_at": datetime.now(UTC).isoformat()}

    def sync(*_args):
        held()
        return {"status": "verified"}

    with runtime._checkpoint(config) as (directory, state):
        state["sources"]["fixture"] = {"snapshot_id": snapshot, "result": {"verification": {"structural_check_pending": True}}}
        state["offsite"] = {"pending_snapshot_ids": [snapshot]}
        runtime._save_json(directory / "state.json", state)
    adapter.check.side_effect = check
    monkeypatch.setattr(runtime, "ResticAdapter", lambda _: adapter)
    monkeypatch.setattr(runtime, "_sync", sync)
    assert runtime.sync_repository_batch({pair: repository_env})[pair]["status"] == "verified"
    assert adapter.check.call_count == 1
    assert redis.values == {}


def test_same_repository_maintenance_contention_preserves_original_lease(repository_env, monkeypatch):
    from app.tasks import backup_lock

    redis = _MemoryBackupRedis()
    monkeypatch.setattr(backup_lock, "get_redis", lambda: redis)
    source = "__repository_maintenance__:" + runtime._repository_pair(ResticConfig.from_env(repository_env))
    owner = backup_lock.acquire_backup_lock(source)
    assert owner is not None
    checkpoint = MagicMock(side_effect=AssertionError("no concurrent repository work may start"))
    monkeypatch.setattr(runtime, "_checkpoint", checkpoint)
    with pytest.raises(ResticError, match="maintenance admission"):
        runtime.maintain_repository(repository_env)
    assert redis.values == {backup_lock.BACKUP_LOCK_PREFIX + source: owner}
    checkpoint.assert_not_called()
    assert backup_lock.release_backup_lock(source, owner)


def test_repository_maintenance_unknown_admission_fails_closed(repository_env, monkeypatch):
    from app.tasks import backup_lock

    def unavailable():
        raise ConnectionError("synthetic Redis unavailable")

    monkeypatch.setattr(backup_lock, "get_redis", unavailable)
    checkpoint = MagicMock(side_effect=AssertionError("no repository work may start"))
    monkeypatch.setattr(runtime, "_checkpoint", checkpoint)
    with pytest.raises(ResticError, match="maintenance admission"):
        runtime.maintain_repository(repository_env)
    checkpoint.assert_not_called()


def test_maintenance_lease_covers_restore_checks_retention_prune_and_catalogue(repository_env, monkeypatch):
    from app.tasks import backup_lock

    redis = _MemoryBackupRedis()
    monkeypatch.setattr(backup_lock, "get_redis", lambda: redis)
    env = {**repository_env, "RESTIC_OFFSITE_PRUNE_QUALIFIED": "true"}
    Path(env["RESTIC_LOCAL_REPOSITORY"]).mkdir()
    source = "__repository_maintenance__:" + runtime._repository_pair(ResticConfig.from_env(env))
    expected = backup_lock.BACKUP_LOCK_PREFIX + source
    phases = []

    def held(phase):
        phases.append(phase)
        assert set(redis.values) == {expected}

    def restore(*_args, **_kwargs):
        held("restore")
        return {"status": "verified"}

    def check(**_kwargs):
        held("check")
        return {"verified": True, "state": {}, "checked_at": datetime.now(UTC).isoformat()}

    def retain(*_args, **_kwargs):
        held("retention")
        return {"status": "completed"}

    def prune(**_kwargs):
        held("prune")
        with pytest.raises(backup_lock.BackupLockLeaseError, match="Backups active"), backup_lock.backup_worker_restart_guard():
            pytest.fail("prune must remain protected from restart")
        return {"status": "skipped", "reason": "weekly-cadence"}

    def catalogue(*_args):
        held("catalogue")
        return 0

    adapter = MagicMock()
    adapter.check.side_effect = check
    adapter.retention.side_effect = retain
    adapter.prune.side_effect = prune
    adapter.quota_free_bytes.return_value = 1024**3
    monkeypatch.setattr(runtime, "ResticAdapter", lambda _: adapter)
    monkeypatch.setattr(runtime, "_weekly_critical_restore", restore)
    monkeypatch.setattr(runtime, "_reconcile_catalogue", catalogue)
    monkeypatch.setattr(runtime.backup_store, "list_sources", lambda: [])

    assert runtime.maintain_repository(env, dry_run=False)["status"] == "completed"
    assert phases == ["restore", "check", "check", "retention", "prune", "retention", "prune", "catalogue"]
    assert redis.values == {}


@pytest.fixture
def critical_link_replay(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest):
    """Replay the canonical Claude zzconsult link with real capture/restore helpers."""
    from app.tasks import backup_native_recovery as recovery

    skills = tmp_path / "agent-skills"
    (skills / "skills/available").mkdir(parents=True)
    (skills / "skills/available/SKILL.md").write_text("synthetic usable skill")
    if getattr(request, "param", False):
        (skills / "skills/zzconsult").mkdir()
        (skills / "skills/zzconsult/SKILL.md").write_text("synthetic mapped target")
    claude = tmp_path / "claude-config"
    (claude / "skills").mkdir(parents=True)
    (claude / "skills/available").symlink_to(skills / "skills/available")
    (claude / "skills/zzconsult").symlink_to(skills / "skills/zzconsult")
    rows = {}
    archives = {}
    for index, (source_id, source) in enumerate((("agent-skills", skills), ("claude-config", claude)), 1):
        snapshot, _ = recovery.build_consistent_snapshot(
            source, tmp_path / ("stage-" + source_id), (), lambda *_: False,
            source_roots={"agent-skills": skills},
        )
        archive = tmp_path / (source_id + ".tar.gz")
        with tarfile.open(archive, "w:gz") as payload:
            payload.add(snapshot, arcname=source_id)
        archives[source_id] = archive
        rows[source_id] = {
            "id": "point-" + source_id, "source_id": source_id,
            "storage_backend_id": "stb-fixture", "status": "completed",
            "verification_json": {
                "format": "restic-v1", "snapshot_id": str(index) * 64,
                "remote_snapshot_id": str(index + 2) * 64,
                "offsite": {"status": "verified"},
            },
        }
    monkeypatch.setattr(runtime.backup_store, "list_sources", lambda: [{"id": name, "enabled": True} for name in rows])
    monkeypatch.setattr(runtime.backup_store, "list_backups", lambda *, source_id, **_: ([rows[source_id]], 1))
    materialize = MagicMock(side_effect=lambda row, **_: nullcontext(archives[row["source_id"]]))
    monkeypatch.setattr(runtime, "materialize_repository_archive", materialize)
    return rows, archives, materialize


@pytest.fixture
def critical_infrastructure_replay(critical_link_replay, tmp_path, monkeypatch):
    from app.tasks import backup_restore_drill

    rows, archives, materialize = critical_link_replay
    archives["infrastructure"] = tmp_path / "infrastructure.tar.gz"
    archives["infrastructure"].write_bytes(b"synthetic infrastructure payload")
    rows["infrastructure"] = {
        "id": "point-infrastructure", "source_id": "infrastructure",
        "storage_backend_id": "stb-fixture", "status": "completed",
        "verification_json": {
            "format": "restic-v1", "snapshot_id": "5" * 64,
            "remote_snapshot_id": "6" * 64, "offsite": {"status": "verified"},
        },
    }
    record = MagicMock()
    monkeypatch.setattr(backup_restore_drill, "_record_drill_result", record)
    return rows, archives, materialize, record


def test_unresolved_combined_config_links_skip_infrastructure_restore(critical_infrastructure_replay, monkeypatch):
    from app.tasks import backup_restore_drill

    rows, _, materialize, record = critical_infrastructure_replay
    run = MagicMock(return_value={"ok": True})
    monkeypatch.setattr(backup_restore_drill, "_run_drill_script", run)
    maintenance = {}
    result = runtime._weekly_critical_restore({"BACKUP_STORAGE_BACKEND_ID": "stb-fixture"}, maintenance)

    assert result["status"] == "failed" and result["failed_source"] == "claude-config"
    assert result["sources"]["claude-config"]["mapped_links_pending"]
    assert result["selected_backups"]["infrastructure"]["backup_id"] == rows["infrastructure"]["id"]
    assert [call.args[0]["source_id"] for call in materialize.call_args_list] == ["agent-skills", "claude-config"]
    assert all(call.kwargs == {"remote": True} for call in materialize.call_args_list)
    run.assert_not_called()
    record.assert_not_called()
    assert maintenance["critical_restore_failure"] == result
    assert "critical_restore_success" not in maintenance and "critical_restore_at" not in maintenance


@pytest.mark.parametrize("critical_link_replay", [True], indirect=True)
@pytest.mark.parametrize("drill_ok", [False, True])
def test_complete_config_links_still_require_infrastructure_drill(critical_infrastructure_replay, monkeypatch, drill_ok):
    from app.tasks import backup_executor, backup_restore_drill

    _, archives, materialize, record = critical_infrastructure_replay
    completed = []
    original = backup_executor._complete_mapped_recovery

    def mapped(target, roots):
        result = original(target, roots)
        assert result["recovery_complete"] is True
        completed.append(target.name)
        return result

    def drill(archive, backup_id):
        assert completed == ["agent-skills", "claude-config"]
        assert archive == str(archives["infrastructure"]) and backup_id == "point-infrastructure"
        return {"ok": drill_ok}

    monkeypatch.setattr(backup_executor, "_complete_mapped_recovery", mapped)
    run = MagicMock(side_effect=drill)
    monkeypatch.setattr(backup_restore_drill, "_run_drill_script", run)
    maintenance = {}
    result = runtime._weekly_critical_restore({"BACKUP_STORAGE_BACKEND_ID": "stb-fixture"}, maintenance)

    run.assert_called_once()
    record.assert_called_once_with("infrastructure", "point-infrastructure", ok=drill_ok, result={"ok": drill_ok})
    assert [call.args[0]["source_id"] for call in materialize.call_args_list] == ["agent-skills", "claude-config", "infrastructure"]
    assert all(call.kwargs == {"remote": True} for call in materialize.call_args_list)
    assert result["status"] == ("verified" if drill_ok else "failed")
    if drill_ok:
        assert maintenance["critical_restore_success"] == result
        assert "critical_restore_at" in maintenance
    else:
        assert result["failed_source"] == "infrastructure"
        assert maintenance["critical_restore_failure"] == result
        assert "critical_restore_success" not in maintenance and "critical_restore_at" not in maintenance


def test_critical_restore_retains_actual_dangling_mapping_and_selected_points(critical_link_replay):
    rows, _, _ = critical_link_replay
    maintenance = {}
    result = runtime._weekly_critical_restore({"BACKUP_STORAGE_BACKEND_ID": "stb-fixture"}, maintenance)

    assert result["status"] == "failed"
    assert result["failed_source"] == "claude-config"
    assert result["error"] == "Canonical configuration links remain unresolved"
    assert result["sources"]["claude-config"].get("recovery_complete") is False
    assert result["sources"]["claude-config"]["mapped_links_restored"] == 1
    assert result["sources"]["claude-config"]["mapped_links_pending"] == [{
        "path": "skills/zzconsult", "target_source": "agent-skills", "target_relative_path": "skills/zzconsult",
    }]
    assert result["selected_backups"]["claude-config"]["backup_id"] == rows["claude-config"]["id"]
    assert "critical_restore_at" not in maintenance


def test_failed_critical_restore_reuses_failure_but_changed_snapshot_retries(critical_link_replay):
    rows, _, materialize = critical_link_replay
    maintenance = {}
    env = {"BACKUP_STORAGE_BACKEND_ID": "stb-fixture"}
    first = runtime._weekly_critical_restore(env, maintenance)
    second = runtime._weekly_critical_restore(env, maintenance)

    assert first["status"] == second["status"] == "failed"
    assert second["cached"] is True
    assert second["reason"] == "unchanged-failed-recovery-inputs"
    assert second["sources"]["claude-config"]["mapped_links_pending"] == first["sources"]["claude-config"]["mapped_links_pending"]
    assert materialize.call_count == 2
    rows["agent-skills"]["verification_json"]["remote_snapshot_id"] = "9" * 64
    third = runtime._weekly_critical_restore(env, maintenance)
    assert third["status"] == "failed"
    assert third["input_fingerprint"] != first["input_fingerprint"]
    assert materialize.call_count == 4


def test_failed_restore_catalogue_only_changes_do_not_repeat_drill(critical_link_replay):
    rows, _, materialize = critical_link_replay
    maintenance = {}
    env = {"BACKUP_STORAGE_BACKEND_ID": "stb-fixture"}
    first = runtime._weekly_critical_restore(env, maintenance)
    for row in rows.values():
        row["id"] = "new-catalogue-row-" + row["source_id"]

    result = runtime._weekly_critical_restore(env, maintenance)
    assert result["status"] == "failed"
    assert result.get("cached") is True
    assert result["input_fingerprint"] == first["input_fingerprint"]
    assert materialize.call_count == 2


def test_failed_restore_retries_changed_implementation_and_force(critical_link_replay, monkeypatch):
    _, _, materialize = critical_link_replay
    maintenance = {}
    env = {"BACKUP_STORAGE_BACKEND_ID": "stb-fixture"}
    monkeypatch.setattr(runtime, "_critical_restore_implementation_fingerprint", lambda: "first-implementation")
    runtime._weekly_critical_restore(env, maintenance)
    monkeypatch.setattr(runtime, "_critical_restore_implementation_fingerprint", lambda: "repaired-implementation")
    runtime._weekly_critical_restore(env, maintenance)
    assert materialize.call_count == 4
    runtime._weekly_critical_restore(env, maintenance, force=True)
    assert materialize.call_count == 6


def test_repaired_mapping_succeeds_and_keeps_weekly_cadence(critical_link_replay):
    rows, archives, materialize = critical_link_replay
    maintenance = {}
    env = {"BACKUP_STORAGE_BACKEND_ID": "stb-fixture"}
    runtime._weekly_critical_restore(env, maintenance)
    # Replay a newly captured Claude point after retiring its obsolete link.
    archive = archives["claude-config"]
    with tarfile.open(archive, "r:gz") as payload:
        members = []
        for member in payload.getmembers():
            stream = payload.extractfile(member) if member.isfile() else None
            members.append((member, stream.read() if stream is not None else None))
    with tarfile.open(archive, "w:gz") as payload:
        for member, data in members:
            if member.name.endswith("/manifest.json"):
                assert data is not None
                manifest = json.loads(data)
                manifest["mapped_links"] = [mapping for mapping in manifest["mapped_links"] if mapping["path"] != "skills/zzconsult"]
                data = json.dumps(manifest).encode()
                member.size = len(data)
            payload.addfile(member, BytesIO(data) if data is not None else None)
    rows["claude-config"]["verification_json"]["remote_snapshot_id"] = "8" * 64

    result = runtime._weekly_critical_restore(env, maintenance)
    assert result["status"] == "verified"
    assert result["sources"]["claude-config"]["recovery_complete"] is True
    assert result["sources"]["claude-config"]["mapped_links_pending"] == []
    assert "critical_restore_failure" not in maintenance
    assert maintenance["critical_restore_success"] == result
    calls = materialize.call_count
    assert runtime._weekly_critical_restore(env, maintenance)["reason"] == "weekly-cadence"
    assert materialize.call_count == calls
    assert maintenance["critical_restore_success"] == result
    maintenance["critical_restore_at"] = (datetime.now(UTC) - timedelta(days=8)).isoformat()
    assert runtime._weekly_critical_restore(env, maintenance)["status"] == "verified"
    assert materialize.call_count == calls + 2


def test_cached_failed_restore_blocks_qualified_retention(repository_env, critical_link_replay, monkeypatch):
    _, _, materialize = critical_link_replay
    env = {**repository_env, "RESTIC_OFFSITE_PRUNE_QUALIFIED": "true"}
    Path(env["RESTIC_LOCAL_REPOSITORY"]).mkdir()
    adapter = MagicMock()
    adapter.check.return_value = {"verified": True, "state": {}, "checked_at": datetime.now(UTC).isoformat()}
    monkeypatch.setattr(runtime, "ResticAdapter", lambda _: adapter)
    first = runtime.maintain_repository(env, dry_run=False)
    second = runtime.maintain_repository(env, dry_run=False)

    assert first["status"] == second["status"] == "failed"
    assert second["critical_restore"]["cached"] is True
    assert materialize.call_count == 2
    adapter.retention.assert_not_called()
    adapter.prune.assert_not_called()
    assert runtime.maintain_repository(env, dry_run=False, force_critical_restore=True)["status"] == "failed"
    assert materialize.call_count == 4
    adapter.retention.assert_not_called()
    adapter.prune.assert_not_called()
    with runtime._checkpoint(ResticConfig.from_env(env)) as (_, state):
        assert state["maintenance"]["critical_restore_result"]["status"] == "failed"


def test_failed_restore_cache_survives_subsequent_monthly_check_error(repository_env, critical_link_replay, monkeypatch):
    _, _, materialize = critical_link_replay
    adapter = MagicMock()
    adapter.check.side_effect = ResticError("synthetic repository check unavailable")
    monkeypatch.setattr(runtime, "ResticAdapter", lambda _: adapter)
    for _ in range(2):
        with pytest.raises(ResticError, match="repository check unavailable"):
            runtime.maintain_repository(repository_env)
    assert materialize.call_count == 2
    with runtime._checkpoint(ResticConfig.from_env(repository_env)) as (_, state):
        assert state["maintenance"]["critical_restore_result"]["status"] == "failed"


def test_failed_forced_repair_cannot_be_hidden_by_recent_success(critical_link_replay):
    _, _, materialize = critical_link_replay
    maintenance = {
        "critical_restore_at": datetime.now(UTC).isoformat(),
        "critical_restore_result": {"status": "verified"},
    }
    env = {"BACKUP_STORAGE_BACKEND_ID": "stb-fixture"}
    assert runtime._weekly_critical_restore(env, maintenance)["reason"] == "weekly-cadence"
    runtime._weekly_critical_restore(env, maintenance, force=True)
    result = runtime._weekly_critical_restore(env, maintenance)
    assert result["status"] == "failed"
    assert result["cached"] is True
    assert materialize.call_count == 2


@pytest.mark.parametrize("prior_result,allows_cadence", [
    ({"status": "verified"}, True),
    ({"status": "skipped", "reason": "weekly-cadence"}, True),
    ({}, False),
    ({"status": "pending"}, False),
    ({"status": "skipped", "reason": "unrelated-skip"}, False),
])
def test_cadence_requires_affirmative_verified_result(critical_link_replay, prior_result, allows_cadence):
    _, _, materialize = critical_link_replay
    maintenance = {
        "critical_restore_at": datetime.now(UTC).isoformat(),
        "critical_restore_result": prior_result,
    }
    result = runtime._weekly_critical_restore({"BACKUP_STORAGE_BACKEND_ID": "stb-fixture"}, maintenance)
    assert result["status"] == ("skipped" if allows_cadence else "failed")
    assert materialize.call_count == (0 if allows_cadence else 2)


@pytest.mark.parametrize("retry", ["same", "changed", "force"])
def test_failed_repair_survives_missing_coverage_without_pruning(repository_env, critical_link_replay, monkeypatch, retry):
    rows, _, materialize = critical_link_replay
    env = {**repository_env, "RESTIC_OFFSITE_PRUNE_QUALIFIED": "true"}
    config = ResticConfig.from_env(env)
    Path(env["RESTIC_LOCAL_REPOSITORY"]).mkdir()
    adapter = MagicMock()
    adapter.check.return_value = {"verified": True, "state": {}, "checked_at": datetime.now(UTC).isoformat()}
    monkeypatch.setattr(runtime, "ResticAdapter", lambda _: adapter)
    with runtime._checkpoint(config) as (directory, state):
        state["maintenance"] = {
            "critical_restore_at": datetime.now(UTC).isoformat(),
            "critical_restore_result": {"status": "verified"},
        }
        runtime._save_json(directory / "state.json", state)

    first = runtime.maintain_repository(env, dry_run=False, force_critical_restore=True)
    assert first["critical_restore"]["status"] == "failed"
    rows["agent-skills"]["verification_json"]["offsite"]["status"] = "pending"
    missing = runtime.maintain_repository(env, dry_run=False)
    assert missing["critical_restore"]["status"] == "pending"
    assert materialize.call_count == 2
    rows["agent-skills"]["verification_json"]["offsite"]["status"] = "verified"
    if retry == "changed":
        rows["agent-skills"]["verification_json"]["remote_snapshot_id"] = "9" * 64

    result = runtime.maintain_repository(env, dry_run=False, force_critical_restore=retry == "force")
    assert result["critical_restore"]["status"] == "failed"
    assert result["status"] == "failed"
    assert materialize.call_count == (2 if retry == "same" else 4)
    adapter.retention.assert_not_called()
    adapter.prune.assert_not_called()


def test_legacy_failed_restore_gets_one_evidenced_attempt(critical_link_replay):
    _, _, materialize = critical_link_replay
    maintenance = {
        "critical_restore_at": datetime.now(UTC).isoformat(),
        "critical_restore_result": {"status": "failed", "failed_source": "claude-config"},
    }
    env = {"BACKUP_STORAGE_BACKEND_ID": "stb-fixture"}
    assert runtime._weekly_critical_restore(env, maintenance)["status"] == "failed"
    assert runtime._weekly_critical_restore(env, maintenance)["cached"] is True
    assert materialize.call_count == 2


def test_materialization_failure_retains_all_selected_points_and_is_cached(critical_link_replay):
    rows, _, materialize = critical_link_replay
    materialize.side_effect = ResticError("synthetic remote unavailable")
    maintenance = {}
    env = {"BACKUP_STORAGE_BACKEND_ID": "stb-fixture"}
    result = runtime._weekly_critical_restore(env, maintenance)
    assert result["status"] == "failed"
    assert result["failed_source"] == "agent-skills"
    assert result["sources"]["agent-skills"]["ok"] is False
    assert set(result["selected_backups"]) == set(rows)
    assert runtime._weekly_critical_restore(env, maintenance)["cached"] is True
    assert materialize.call_count == 1


def test_recovery_observation_reads_held_checkpoint_and_preserves_success(repository_env, monkeypatch):
    config = ResticConfig.from_env(repository_env)
    verified_at = datetime.now(UTC).isoformat()
    success = {"status": "verified", "verified_at": verified_at, "sources": {"agent-skills": {"ok": True}}}
    failure = {"status": "failed", "attempted_at": verified_at, "failed_source": "claude-config", "error": "PRIVATE_DIAGNOSTIC_SENTINEL", "sources": {"claude-config": {"mapped_links_pending": [{"path": "PRIVATE_PATH_SENTINEL"}]}}}
    with runtime._checkpoint(config) as (directory, state):
        state["maintenance"] = {
            "critical_restore_success": success, "critical_restore_attempt": failure,
            "critical_restore_failure": failure, "critical_restore_result": {"status": "pending", "missing_sources": ["claude-config"]},
        }
        runtime._save_json(directory / "state.json", state)
        monkeypatch.setattr(runtime.time, "sleep", MagicMock(side_effect=AssertionError("status must not wait for checkpoint")))
        result = runtime.repository_recovery_status(repository_env)
    assert result["status"] == "failed"
    assert result["last_success_at"] == verified_at
    assert result["latest_attempt"]["failed_source_id"] == "claude-config"
    assert result["latest_attempt"]["reason"] == "mapped-links-unresolved"
    assert result["verified_source_ids"] == ["agent-skills"]
    assert "PRIVATE_" not in json.dumps(result)


def test_legacy_verified_restore_is_observed_and_hydrated_before_cadence_skip(repository_env, monkeypatch):
    config = ResticConfig.from_env(repository_env)
    config.local_repository.mkdir(mode=0o700)
    now = datetime.now(UTC).isoformat()
    legacy = {
        "status": "verified", "verified_at": now,
        "selected_backups": {"agent-skills": {"backup_id": "legacy-row"}},
        "sources": {"agent-skills": {"ok": True}},
    }
    with runtime._checkpoint(config) as (directory, state):
        state["maintenance"] = {"critical_restore_at": now, "critical_restore_result": legacy}
        runtime._save_json(directory / "state.json", state)
        before = (directory / "state.json").read_bytes()
        observed = runtime.repository_recovery_status(repository_env)
        assert (directory / "state.json").read_bytes() == before  # Observation never migrates state.
    assert observed["verified_source_ids"] == ["agent-skills"]
    assert observed["latest_attempt"]["status"] == "verified"
    adapter = MagicMock()
    adapter.check.return_value = {"verified": True, "state": {}, "checked_at": now}
    adapter.retention.return_value = {"status": "preview"}
    adapter.prune.return_value = {"status": "preview"}
    monkeypatch.setattr(runtime, "ResticAdapter", lambda _: adapter)
    monkeypatch.setattr(runtime.backup_store, "list_sources", lambda: [])
    runtime.maintain_repository(repository_env)
    with runtime._checkpoint(config) as (_, state):
        maintenance = state["maintenance"]
        assert maintenance["critical_restore_result"]["reason"] == "weekly-cadence"
        assert maintenance["critical_restore_success"] == legacy
        assert maintenance["critical_restore_attempt"] == legacy
    observed = runtime.repository_recovery_status(repository_env)
    assert observed["verified_source_ids"] == ["agent-skills"]
    assert observed["last_success_at"] == now
    assert observed["latest_attempt"]["status"] == "verified"


def test_forced_failure_preserves_legacy_success_before_overwrite(critical_link_replay):
    legacy = {"status": "verified", "verified_at": datetime.now(UTC).isoformat(), "sources": {"agent-skills": {"ok": True}}}
    maintenance: dict[str, Any] = {"critical_restore_at": legacy["verified_at"], "critical_restore_result": legacy}
    result = runtime._weekly_critical_restore({"BACKUP_STORAGE_BACKEND_ID": "stb-fixture"}, maintenance, force=True)
    assert result["status"] == "failed"
    assert maintenance["critical_restore_success"] == legacy
    assert maintenance["critical_restore_attempt"]["status"] == "failed"


def test_running_critical_attempt_is_persisted_before_materialization(repository_env, critical_link_replay, monkeypatch):
    _, _, materialize = critical_link_replay
    observed = []
    original = materialize.side_effect

    def observe_then_materialize(*args, **kwargs):
        observed.append(runtime.repository_recovery_status(repository_env))
        return original(*args, **kwargs)

    materialize.side_effect = observe_then_materialize
    adapter = MagicMock()
    adapter.check.return_value = {"verified": True, "state": {}, "checked_at": datetime.now(UTC).isoformat()}
    monkeypatch.setattr(runtime, "ResticAdapter", lambda _: adapter)
    runtime.maintain_repository(repository_env)
    assert observed[0]["status"] == "running"
    assert observed[0]["latest_attempt"]["status"] == "running"
    assert runtime.repository_recovery_status(repository_env)["status"] == "failed"


@pytest.mark.parametrize("invalid", ["PRIVATE_TIMESTAMP_SENTINEL", {"secret": "PRIVATE_SENTINEL"}, "2026-10-08T12:00:00"])
def test_recovery_observation_rejects_invalid_timestamps(repository_env, invalid):
    config = ResticConfig.from_env(repository_env)
    with runtime._checkpoint(config) as (directory, state):
        state["maintenance"] = {"critical_restore_attempt": {"status": "failed", "attempted_at": invalid}}
        runtime._save_json(directory / "state.json", state)
    result = runtime.repository_recovery_status(repository_env)
    assert result["status"] == "unavailable"
    assert result["latest_attempt"] is None
    assert "PRIVATE" not in json.dumps(result)


def test_genuine_repository_notifications_dedupe_failures_and_report_recovery(repository_env, monkeypatch):
    notify = MagicMock(return_value={"id": "notification"})
    monkeypatch.setattr(runtime, "create_notification", notify)
    state = {}
    failure = {"status": "failed", "failed_source": "claude-config", "error": "PRIVATE_SECRET_SENTINEL"}
    runtime._notify_repository_result(state, repository_env, "critical-restore", failure)
    runtime._notify_repository_result(state, repository_env, "critical-restore", {**failure, "cached": True})
    runtime._notify_repository_result(state, repository_env, "critical-restore", {"status": "pending"})
    runtime._notify_repository_result(state, repository_env, "critical-restore", {"status": "skipped", "reason": "weekly-cadence"})
    assert notify.call_count == 1
    runtime._notify_repository_result(state, repository_env, "local-integrity", {"verified": False})
    assert notify.call_count == 2
    assert notify.call_args.kwargs["dedupe_key"] != notify.call_args_list[0].kwargs["dedupe_key"]
    runtime._notify_repository_result(state, repository_env, "critical-restore", {"status": "verified"})
    runtime._notify_repository_result(state, repository_env, "critical-restore", {"status": "verified"})
    assert notify.call_count == 3
    assert notify.call_args.kwargs["severity"] == "info"
    assert "PRIVATE_" not in str(notify.call_args_list)


def test_structural_success_does_not_notify_recovery_from_payload_failure(repository_env, monkeypatch):
    notify = MagicMock(return_value={"id": "notification"})
    monkeypatch.setattr(runtime, "create_notification", notify)
    state = {}
    runtime._notify_repository_result(state, repository_env, "local-integrity", {"verified": False, "method": "restic-monthly-bucket"})
    runtime._notify_repository_result(state, repository_env, "local-integrity", {"verified": True, "method": "restic-structural-check"})
    assert notify.call_count == 1
    runtime._notify_repository_result(state, repository_env, "local-integrity", {"verified": True, "method": "restic-monthly-bucket"})
    assert notify.call_count == 2
    state = {}
    runtime._notify_repository_result(state, repository_env, "local-integrity", {"verified": False, "method": "restic-structural-check"})
    runtime._notify_repository_result(state, repository_env, "local-integrity", {"verified": True, "method": "restic-monthly-bucket"})
    assert notify.call_count == 4  # Payload verification includes structural checks.


@pytest.mark.parametrize("different_structural_failure", [False, True])
def test_monthly_failure_scope_survives_dedup_and_later_structural_failure(repository_env, monkeypatch, different_structural_failure):
    notify = MagicMock(return_value={"id": "notification"})
    monkeypatch.setattr(runtime, "create_notification", notify)
    state = {}
    runtime._notify_repository_result(state, repository_env, "local-integrity", {"verified": False, "method": "restic-structural-check"})
    runtime._notify_repository_result(state, repository_env, "local-integrity", {"verified": False, "method": "restic-monthly-bucket"})
    assert notify.call_count == 1  # Same failure does not produce another alert.
    assert state["repository_notifications"]["local-integrity"]["method"] == "restic-monthly-bucket"
    if different_structural_failure:
        runtime._notify_repository_result(state, repository_env, "local-integrity", {
            "verified": False, "method": "restic-structural-check", "error": "failed to lock repository",
        })
        assert notify.call_count == 2
        assert state["repository_notifications"]["local-integrity"]["method"] == "restic-monthly-bucket"
    calls = notify.call_count
    runtime._notify_repository_result(state, repository_env, "local-integrity", {"verified": True, "method": "restic-structural-check"})
    assert notify.call_count == calls
    assert state["repository_notifications"]["local-integrity"]["active"] is True
    runtime._notify_repository_result(state, repository_env, "local-integrity", {"verified": True, "method": "restic-monthly-bucket"})
    assert notify.call_count == calls + 1
    assert state["repository_notifications"]["local-integrity"]["active"] is False


def test_failed_monthly_check_keeps_its_mode_through_passing_batch_check(repository_env, monkeypatch):
    config = ResticConfig.from_env(repository_env)
    adapter = MagicMock()
    now = datetime.now(UTC).isoformat()
    # The real adapter omits method on its failed result.
    adapter.check.side_effect = [
        {"status": "failed", "verified": False, "state": {}, "error": "PRIVATE_FAILURE"},
        {"status": "verified", "verified": True, "state": {}, "checked_at": now},
    ]
    monkeypatch.setattr(runtime, "ResticAdapter", lambda _: adapter)
    monkeypatch.setattr(runtime.backup_store, "list_sources", lambda: [])
    monkeypatch.setattr(runtime, "_weekly_critical_restore", lambda *_args, **_kwargs: {"status": "skipped", "reason": "weekly-cadence"})
    notify = MagicMock(return_value={"id": "notification"})
    monkeypatch.setattr(runtime, "create_notification", notify)
    assert runtime.maintain_repository(repository_env)["status"] == "failed"
    assert notify.call_count == 1
    with runtime._checkpoint(config) as (directory, state):
        assert state["repository_notifications"]["local-integrity"]["method"] == "restic-monthly-bucket"
        state["sources"]["fixture"] = {
            "snapshot_id": "a" * 64,
            "result": {"verification": {"structural_check_pending": True, "offsite": {"status": "verified"}}},
        }
        runtime._save_json(directory / "state.json", state)
    adapter.repository_identity.return_value = {"id": "b" * 64}
    adapter.check.side_effect = None
    adapter.check.return_value = {"verified": True, "checked_at": now}
    pair = runtime._repository_pair(config)
    assert runtime.sync_repository_batch({pair: repository_env})[pair]["status"] == "skipped"
    assert notify.call_count == 1
    with runtime._checkpoint(config) as (_, state):
        assert state["repository_notifications"]["local-integrity"]["active"] is True
        assert state["maintenance"]["local"]["monthly_result"]["verified"] is False


def test_notification_failure_does_not_suppress_backup_failure(repository_env, monkeypatch):
    notify = MagicMock(side_effect=RuntimeError("notification storage unavailable"))
    monkeypatch.setattr(runtime, "create_notification", notify)
    state = {}
    failure = {"status": "failed", "failed_source": "claude-config"}
    runtime._notify_repository_result(state, repository_env, "critical-restore", failure)
    assert not state["repository_notifications"]
    runtime._notify_repository_result(state, repository_env, "critical-restore", failure)
    assert notify.call_count == 2


@pytest.fixture
def repository_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    from app.tasks import backup_lock

    redis = _MemoryBackupRedis()
    monkeypatch.setattr(backup_lock, "get_redis", lambda: redis)
    monkeypatch.setattr(runtime, "create_notification", MagicMock(return_value={"id": "notification"}))
    monkeypatch.setenv("SF_HOST_RETENTION_PRESSURE_MIN_FREE_GB", "0")
    keys = tmp_path / "keys"
    keys.mkdir(mode=0o700)
    monkeypatch.setattr(runtime, "backup_key_directory", lambda: keys)
    monkeypatch.setattr(runtime.backup_store, "list_backups", lambda **_: ([], 0))
    monkeypatch.setattr(runtime.backup_store, "list_backends", lambda **_: [])
    for name in ("local-password", "remote-password"):
        (keys / name).touch(mode=0o600)
        (keys / name).write_text(f"synthetic-fixture-{name}\n")
    return {
        "BACKUP_ENGINE": "restic", "BACKUP_STORAGE_BACKEND_ID": "stb-fixture",
        "RESTIC_LOCAL_REPOSITORY": str(tmp_path / "local"),
        "RESTIC_REMOTE_REPOSITORY": str(tmp_path / "remote"),
        "RESTIC_LOCAL_PASSWORD_FILE": str(keys / "local-password"),
        "RESTIC_REMOTE_PASSWORD_FILE": str(keys / "remote-password"),
        "RESTIC_KEY_DIRECTORY": str(keys), "RESTIC_HOSTNAME": "fixture",
    }


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def test_atomic_checkpoint_permissions_and_symlinks(repository_env: dict[str, str], tmp_path: Path) -> None:
    config = ResticConfig.from_env(repository_env)
    with runtime._checkpoint(config) as (directory, state):
        state["sources"]["fixture"] = {"snapshot_id": "a" * 64}
        runtime._save_json(directory / "state.json", state)
        assert (directory / "state.json").stat().st_mode & 0o777 == 0o600
    with runtime._checkpoint(config) as (_, state):
        assert state["sources"]["fixture"]["snapshot_id"] == "a" * 64
    unsafe = tmp_path / "unsafe.json"
    unsafe.symlink_to(directory / "state.json")
    with pytest.raises(ResticError, match="private regular file"):
        runtime._load_json(unsafe)


@pytest.mark.parametrize("capture_fails", [False, True])
def test_repository_capture_uses_private_stable_scratch_and_cleans_attempt(repository_env, tmp_path, monkeypatch, capture_fails):
    source = tmp_path / "source"
    source.mkdir()
    (source / "work.txt").write_text("unsaved work")
    monkeypatch.setattr(runtime, "canonical_backup_source_roots", lambda: {})
    monkeypatch.setattr(runtime, "record_local_archive", lambda _: None)
    monkeypatch.setenv("TMPDIR", "/caller/namespace")
    captures = []

    def save_payload(_adapter, _source_id, payload):
        snapshot = payload["snapshot_dir"]
        captures.append(snapshot)
        assert snapshot.is_relative_to(transient_scratch.SCRATCH_ROOT)
        assert snapshot.parent.stat().st_mode & 0o777 == 0o700
        assert (snapshot / "work.txt").read_text() == ("unsaved work" if len(captures) == 1 else "edited work")
        child_env = transient_scratch.scratch_subprocess_env()
        assert Path(child_env["TMPDIR"]) == snapshot.parent / "tmp"
        assert Path(child_env["XDG_CACHE_HOME"]) == snapshot.parent / "cache"
        if capture_fails:
            raise ResticError("synthetic capture failure")
        return {"snapshot_id": "a" * 64, "repository_id": "b" * 64, "location": "restic-v1:fixture", "verification": {"verified": True, "capture": {}}}

    monkeypatch.setattr(ResticAdapter, "save_payload", save_payload)
    for _ in range(2):
        if capture_fails:
            with pytest.raises(ResticError, match="synthetic capture failure"):
                runtime.run_repository_backup(project_dir=str(source), source_id="fixture", env=repository_env, local_only=True)
        else:
            runtime.run_repository_backup(project_dir=str(source), source_id="fixture", env=repository_env, local_only=True)
        assert not captures[-1].parent.exists()
        (source / "work.txt").write_text("edited work")
        with runtime._checkpoint(ResticConfig.from_env(repository_env)) as (directory, state):
            if not capture_fails:
                assert state["sources"]["fixture"]["snapshot_id"] == "a" * 64
            assert directory.is_relative_to(Path(repository_env["RESTIC_KEY_DIRECTORY"]))
            assert not (directory / "payloads").exists()
    assert captures[0] == captures[1]
    assert os.environ["TMPDIR"] == "/caller/namespace"


@pytest.mark.parametrize("unsafe", ["missing", "unmounted", "shared", "private-link", "staging-link"])
def test_repository_capture_refuses_unsafe_scratch_before_materializing(repository_env, tmp_path, monkeypatch, unsafe):
    root = transient_scratch.SCRATCH_ROOT
    if unsafe == "missing":
        monkeypatch.setattr(transient_scratch, "SCRATCH_ROOT", tmp_path / "missing")
    elif unsafe == "unmounted":
        monkeypatch.setattr(Path, "is_mount", lambda _: False)
    elif unsafe == "shared":
        root.chmod(0o777)
    elif unsafe == "private-link":
        (root / f"st-backup-captures-{os.getuid()}").symlink_to(tmp_path)
    else:
        pair = runtime._repository_pair(ResticConfig.from_env(repository_env))
        payloads = root / f"st-backup-captures-{os.getuid()}" / pair / "payloads"
        payloads.mkdir(parents=True, mode=0o700)
        payloads.parent.chmod(0o700)
        payloads.parent.parent.chmod(0o700)
        protected = tmp_path / "protected"
        protected.mkdir()
        (protected / "keep.txt").write_text("unrelated source")
        staging_link = payloads / runtime.hashlib.sha256(b"fixture").hexdigest()
        staging_link.symlink_to(protected)
    save = MagicMock(side_effect=AssertionError("unsafe scratch must not capture"))
    monkeypatch.setattr(ResticAdapter, "save_payload", save)
    with pytest.raises((transient_scratch.ScratchError, ResticError), match=r"unsafe|symlink"):
        runtime.run_repository_backup(project_dir=str(tmp_path), source_id="fixture", env=repository_env, local_only=True)
    save.assert_not_called()
    assert not list(Path(repository_env["RESTIC_KEY_DIRECTORY"]).glob("restic-state/*/payloads"))
    if unsafe == "staging-link":
        assert staging_link.is_symlink()
        assert (protected / "keep.txt").read_text() == "unrelated source"


def test_repository_capture_reclaims_interrupted_private_stage_before_capacity_admission(repository_env, tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    (source / "work.txt").write_text("unsaved work")
    config = ResticConfig.from_env(repository_env)
    scratch = transient_scratch.mounted_scratch_parent("st-backup-captures")
    assert scratch is not None
    staging = scratch / runtime._repository_pair(config) / "payloads" / runtime.hashlib.sha256(b"fixture").hexdigest()
    runtime._private_directory(staging.parent.parent)
    runtime._private_directory(staging.parent)
    runtime._private_directory(staging)
    leftover = staging / "interrupted-plaintext"
    leftover.write_bytes(b"owned disposable fixture")
    unrelated = staging.parent / "unrelated-source"
    unrelated.mkdir(mode=0o700)
    (unrelated / "keep.txt").write_text("other capture")
    monkeypatch.setenv("SF_HOST_RETENTION_PRESSURE_MIN_FREE_GB", "25")
    monkeypatch.setattr(runtime, "canonical_backup_source_roots", lambda: {})
    monkeypatch.setattr(runtime, "record_local_archive", lambda _: None)
    usage = shutil.disk_usage(tmp_path)
    reserve = 25 * 1024**3

    def free_after_reclaim(_path):
        return usage._replace(free=reserve - 1 if leftover.exists() else 100 * 1024**3)

    monkeypatch.setattr(runtime.shutil, "disk_usage", free_after_reclaim)
    saved = {"snapshot_id": "a" * 64, "repository_id": "b" * 64, "location": "restic-v1:fixture", "verification": {"verified": True, "capture": {}}}
    monkeypatch.setattr(ResticAdapter, "save_payload", lambda *_: saved)
    result = runtime.run_repository_backup(project_dir=str(source), source_id="fixture", env=repository_env, local_only=True)
    assert result["snapshot_id"] == "a" * 64
    assert not staging.exists()
    assert (unrelated / "keep.txt").read_text() == "other capture"


@pytest.mark.parametrize("phase", ["before", "after"])
def test_repository_capture_admits_actual_scratch_destination_and_cleans_capacity_failure(repository_env, tmp_path, monkeypatch, phase):
    source = tmp_path / "source"
    source.mkdir()
    (source / "work.txt").write_text("unsaved work")
    config = ResticConfig.from_env(repository_env)
    with runtime._checkpoint(config) as (directory, state):
        state["sources"]["fixture"] = {"capacity": {"staging_peak_bytes": 100}}
        runtime._save_json(directory / "state.json", state)
    monkeypatch.setenv("SF_HOST_RETENTION_PRESSURE_MIN_FREE_GB", "25")
    monkeypatch.setattr(runtime, "canonical_backup_source_roots", lambda: {})
    usage = shutil.disk_usage(tmp_path)
    observed = []
    reserve = 25 * 1024**3

    def destination_usage(path):
        path = Path(path)
        observed.append(path)
        if path.is_relative_to(transient_scratch.SCRATCH_ROOT):
            if phase == "before":
                return usage._replace(free=reserve + 99)
            if (path / "project-snapshot").exists():
                return usage._replace(free=reserve - 1)
        return usage._replace(free=100 * 1024**3)

    monkeypatch.setattr(runtime.shutil, "disk_usage", destination_usage)
    save = MagicMock(side_effect=AssertionError("insufficient destination capacity must not capture"))
    monkeypatch.setattr(ResticAdapter, "save_payload", save)
    with pytest.raises((ResticError, transient_scratch.ScratchError), match=r"insufficient host-policy headroom|Insufficient restore scratch space"):
        runtime.run_repository_backup(project_dir=str(source), source_id="fixture", env=repository_env, local_only=True)
    save.assert_not_called()
    assert any(path.is_relative_to(transient_scratch.SCRATCH_ROOT) for path in observed)
    assert config.key_directory not in observed
    assert not list(transient_scratch.SCRATCH_ROOT.glob("st-backup-captures-*/*/payloads/*"))


def test_previous_capture_bundle_stays_on_scratch_and_counts_toward_staging_peak(repository_env, tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    (source / "work.txt").write_text("unsaved work")
    config = ResticConfig.from_env(repository_env)
    with runtime._checkpoint(config) as (directory, state):
        state["sources"]["fixture"] = {"snapshot_id": "c" * 64, "recovery": {"git": {"head": "fixture"}}}
        runtime._save_json(directory / "state.json", state)
    monkeypatch.setattr(runtime, "canonical_backup_source_roots", lambda: {})
    monkeypatch.setattr(runtime, "record_local_archive", lambda _: None)
    restored = []

    def restore(_adapter, _snapshot_id, destination, **_kwargs):
        assert destination.is_relative_to(transient_scratch.SCRATCH_ROOT)
        restored.append(destination)
        recovery = destination / runtime.RECOVERY_DIR_NAME
        recovery.mkdir()
        (recovery / runtime.GIT_BUNDLE_NAME).write_bytes(b"x" * 16384)
        return {"payload_root": str(destination)}

    saved = {"snapshot_id": "a" * 64, "repository_id": "b" * 64, "location": "restic-v1:fixture", "verification": {"verified": True, "capture": {}}}
    monkeypatch.setattr(ResticAdapter, "restore", restore)
    monkeypatch.setattr(ResticAdapter, "save_payload", lambda *_: saved)
    runtime.run_repository_backup(project_dir=str(source), source_id="fixture", env=repository_env, local_only=True)
    assert len(restored) == 1
    assert not restored[0].parent.exists()
    with runtime._checkpoint(config) as (_, state):
        assert state["sources"]["fixture"]["capacity"]["staging_peak_bytes"] >= 16384


def test_sql_failure_leaves_durable_local_reference_and_no_plaintext(repository_env: dict[str, str], tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "work.txt").write_text("unsaved work")
    config = ResticConfig.from_env(repository_env)
    saved = {"snapshot_id": "a" * 64, "repository_id": "b" * 64, "location": "restic-v1:fixture", "verification": {"verified": True, "capture": {}}}
    with patch.object(runtime, "canonical_backup_source_roots", return_value={}), patch.object(ResticAdapter, "save_payload", return_value=saved), patch.object(runtime, "record_local_archive", side_effect=RuntimeError("SQL unavailable")), pytest.raises(RuntimeError, match="SQL unavailable"):
        runtime.run_repository_backup(project_dir=str(source), source_id="fixture", env=repository_env)
    with runtime._checkpoint(config) as (directory, state):
        assert state["sources"]["fixture"]["snapshot_id"] == "a" * 64
        assert not (directory / "payloads").exists()
        assert not list(transient_scratch.SCRATCH_ROOT.glob("st-backup-captures-*/*/payloads/*"))


def test_recorded_backend_required_no_current_default_fallback() -> None:
    with pytest.raises(ResticError, match="default fallback refused"):
        runtime._backup_environment({"source_id": "fixture", "verification_json": {"format": "restic-v1"}})


def test_codex_essentials_does_not_download_previous_git_bundle(repository_env: dict[str, str], tmp_path: Path) -> None:
    source = tmp_path / ".codex"
    source.mkdir()
    (source / "AGENTS.md").write_text("custom instructions")
    saved = {"snapshot_id": "a" * 64, "repository_id": "b" * 64, "location": "restic-v1:fixture", "verification": {"verified": True, "capture": {}}}
    with (
        patch.object(runtime, "canonical_backup_source_roots", return_value={}),
        patch.object(runtime, "_previous_bundle", side_effect=AssertionError("unnecessary previous bundle download")),
        patch.object(ResticAdapter, "save_payload", return_value=saved) as save,
        patch.object(runtime, "record_local_archive"),
    ):
        runtime.run_repository_backup(project_dir=str(source), source_id=".codex", env=repository_env, local_only=True)
    assert save.call_args.args[1]["recovery"]["capture_profile"] == "codex-restore-essentials-v1"
    assert save.call_args.args[1]["recovery"]["git"] is None


def test_infrastructure_capture_uses_stable_host_config_root(repository_env, tmp_path) -> None:
    release = tmp_path / "immutable-release"
    release.mkdir()
    host = tmp_path / "stable-host"
    (host / "docker/compose/hatchet-config").mkdir(parents=True)
    (host / "docker/compose/.env").write_text("SYNTHETIC_CONFIG=fixture\n")
    snapshot = tmp_path / "fixture-payload"
    snapshot.mkdir(mode=0o700)
    payload = {"snapshot_dir": snapshot, "total_files": 1, "db_bytes": 1, "recovery": {}, "db_dump_name": "pgdumpall.sql"}
    saved = {"snapshot_id": "a" * 64, "repository_id": "b" * 64, "location": "restic-v1:fixture", "verification": {"verified": True, "capture": {}}}
    with (
        patch.object(runtime, "get_host_config_root", return_value=host),
        patch.object(runtime, "prepare_infrastructure_payload", return_value=payload) as prepare,
        patch.object(ResticAdapter, "save_payload", return_value=saved),
        patch.object(runtime, "record_local_archive"),
    ):
        runtime.run_repository_backup(project_dir=str(release), source_id="infrastructure", env=repository_env, local_only=True, infrastructure=True)
    assert prepare.call_args.args[0] == release
    assert prepare.call_args.kwargs["host_config_root"] == host
    assert not (release / "docker/compose/.env").exists()


def test_initialization_never_overwrites_existing_password(repository_env: dict[str, str]) -> None:
    password = Path(repository_env["RESTIC_LOCAL_PASSWORD_FILE"])
    before = password.stat()
    with patch.object(ResticAdapter, "readiness", return_value={"ready": True}), patch.object(ResticAdapter, "initialize", return_value={"status": "initialized"}):
        result = runtime.initialize_repository(repository_env, local_only=True)
    assert password.stat().st_mtime_ns == before.st_mtime_ns
    assert result["default_changed"] is False
    assert result["recovery_key_escrow_confirmed"] is False


@pytest.mark.skipif(shutil.which("restic") is None, reason="Pinned Restic binary not installed")
def test_real_independent_copy_deduplicates_and_recovers_wip(repository_env: dict[str, str], tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    # Large enough to demonstrate unchanged payload dedup, but only a tiny
    # synthetic fixture; no real conversations or credentials are captured.
    (source / "asset.bin").write_bytes(os.urandom(8 * 1024 * 1024))
    (source / "work.txt").write_text("committed\n")
    _git(source, "init", "-q")
    _git(source, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "add", ".")
    _git(source, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "fixture")
    (source / "work.txt").write_text("staged\n")
    _git(source, "add", "work.txt")
    (source / "work.txt").write_text("working copy\n")
    runtime.initialize_repository(repository_env)
    with patch.object(runtime, "canonical_backup_source_roots", return_value={}):
        first = runtime.run_repository_backup(project_dir=str(source), source_id="fixture", env=repository_env)
        second = runtime.run_repository_backup(project_dir=str(source), source_id="fixture", env=repository_env)
    assert first["verification"]["offsite"]["status"] == "verified"
    assert second["verification"]["offsite"]["status"] == "verified"
    assert second["unchanged"] is True
    assert first["verification"]["repository_id"] != first["verification"]["remote_repository_id"]
    assert second["data_added_bytes"] < first["data_added_bytes"] / 2
    assert second["verification"]["offsite"]["new_object_bytes"] < first["verification"]["offsite"]["new_object_bytes"] / 2
    backup = {"source_id": "fixture", "storage_backend_id": "stb-fixture", "verification_json": second["verification"]}
    with patch.object(runtime, "build_storage_env", return_value=repository_env), runtime.materialize_repository_archive(backup, remote=True) as archive:
        from app.tasks.backup_native_restore import restore_isolated_archive

        restored = restore_isolated_archive(archive, tmp_path / "recovered")
    assert restored["recovery"]["git_restored"] is True
    assert (tmp_path / "recovered" / "work.txt").read_text() == "working copy\n"
    staged = subprocess.run(["git", "-C", str(tmp_path / "recovered"), "show", ":work.txt"], capture_output=True, text=True, check=True)
    assert staged.stdout == "staged\n"
    with runtime._checkpoint(ResticConfig.from_env(repository_env)) as (directory, state):
        assert state["offsite"]["pending_objects"] == []
        assert not (directory / "payloads").exists()
        assert not list(transient_scratch.SCRATCH_ROOT.glob("st-backup-captures-*/*/payloads/*"))
        # The private journal contains references, never password contents.
        assert "synthetic-fixture-local-password" not in json.dumps(state)


@pytest.mark.skipif(shutil.which("restic") is None, reason="Pinned Restic binary not installed")
def test_real_serial_batch_checks_copies_once_and_retries_all_pending(repository_env, tmp_path, monkeypatch):
    runtime.initialize_repository(repository_env)
    monkeypatch.setattr(runtime, "canonical_backup_source_roots", lambda: {})
    sources = [tmp_path / "source-one", tmp_path / "source-two"]
    for source in sources:
        source.mkdir()
        (source / "saved.txt").write_text(source.name)
    config = ResticConfig.from_env(repository_env)
    with patch.object(ResticAdapter, "check", wraps=ResticAdapter(config).check) as checked, patch.object(ResticAdapter, "sync", wraps=ResticAdapter(config).sync) as copied:
        with runtime.repository_capture_batch() as batch:
            first = runtime.run_repository_backup(project_dir=str(sources[0]), source_id="one", env=repository_env)
            second = runtime.run_repository_backup(project_dir=str(sources[1]), source_id="two", env=repository_env)
            assert first["verification"]["structural_check_pending"] is True
            assert first["verification"]["structural_check_at"] is None
            with runtime._checkpoint(config) as (directory, state):
                assert not (directory / "payloads").exists()
                assert not list(transient_scratch.SCRATCH_ROOT.glob("st-backup-captures-*/*/payloads/*"))
                assert state["offsite"]["pending_snapshot_ids"] == [first["snapshot_id"], second["snapshot_id"]]
        checked.assert_not_called()
        copied.assert_not_called()
        with patch.object(ResticAdapter, "sync", side_effect=ResticError("synthetic unavailable offsite")) as unavailable:
            failed = runtime.sync_repository_batch(batch)
            assert next(iter(failed.values()))["status"] == "pending"
            assert unavailable.call_count == 1
        with runtime._checkpoint(config) as (_, state):
            assert state["offsite"]["pending_snapshot_ids"] == [first["snapshot_id"], second["snapshot_id"]]
            assert all(value["result"]["verification"]["offsite"]["status"] == "pending" for value in state["sources"].values())
        results = runtime.sync_repository_batch(batch)
        assert next(iter(results.values()))["status"] == "verified"
        assert checked.call_count == copied.call_count == 1
    with runtime._checkpoint(config) as (_, state):
        assert state["offsite"]["pending_snapshot_ids"] == []
        assert all(value["result"]["verification"]["offsite"]["status"] == "verified" for value in state["sources"].values())
        assert all(value["result"]["verification"]["structural_check_pending"] is False for value in state["sources"].values())
    # Restart retry is independent of newly due captures and includes every
    # retained SQL snapshot, even when checkpoint sources contain newer points.
    old = first["snapshot_id"]
    rows = [{"id": "old-row", "storage_backend_id": "stb-fixture", "status": "completed_pending_upload", "verification_json": {"format": "restic-v1", "repository_id": first["repository_id"], "snapshot_id": old, "offsite": {"status": "pending"}}}]
    monkeypatch.setattr(runtime.backup_store, "list_backups", lambda **_: (rows, 1))
    merged = []
    monkeypatch.setattr(runtime.backup_store, "merge_backup_verification_json", lambda backup_id, update: merged.append((backup_id, update)))
    monkeypatch.setattr(runtime.backup_store, "update_backup_status", lambda *args: None)
    results = runtime.sync_repository_batch(batch)
    assert next(iter(results.values()))["status"] == "verified"
    assert merged[0][0] == "old-row"
    assert merged[0][1]["offsite"]["status"] == "verified"


def test_database_capture_never_reuses_unchanged_files(repository_env, tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    dumped = []
    def dump(project_name, destination, env):
        dumped.append(project_name)
        destination.write_bytes(b"consistent fresh SQL")
        return destination.stat().st_size, True
    monkeypatch.setattr("app.tasks.backup_native_archive._dump_database", dump)
    monkeypatch.setattr(runtime, "canonical_backup_source_roots", lambda: {})
    saved = {"snapshot_id": "a" * 64, "repository_id": "b" * 64, "location": "restic-v1:fixture", "verification": {"verified": True, "capture": {}}}
    (source / "saved.txt").write_text("unchanged files")
    with patch.object(ResticAdapter, "save_payload", side_effect=lambda *_args: json.loads(json.dumps(saved))) as save, patch.object(runtime, "record_local_archive"):
        runtime.run_repository_backup(project_dir=str(source), source_id="source", env=repository_env, local_only=True)
        runtime.run_repository_backup(project_dir=str(source), source_id="source", env=repository_env, local_only=True)
    assert len(dumped) == save.call_count == 2


def test_sqlite_capture_never_reuses_unchanged_database(repository_env, tmp_path, monkeypatch):
    from app.tasks import backup_native_recovery as recovery

    source = tmp_path / "source"
    source.mkdir()
    with sqlite3.connect(source / "records.sqlite") as connection:
        connection.execute("CREATE TABLE fixture (value TEXT)")
        connection.execute("INSERT INTO fixture VALUES ('durable')")
    monkeypatch.setattr(runtime, "canonical_backup_source_roots", lambda: {})
    monkeypatch.setattr("app.tasks.backup_native_archive._dump_database", lambda *_: (0, False))
    saved = {"snapshot_id": "a" * 64, "repository_id": "b" * 64, "location": "restic-v1:fixture", "verification": {"verified": True, "capture": {}}}
    with patch.object(recovery, "_copy_sqlite_database", wraps=recovery._copy_sqlite_database) as capture, patch.object(ResticAdapter, "save_payload", side_effect=lambda *_args: json.loads(json.dumps(saved))) as save, patch.object(runtime, "record_local_archive"):
        runtime.run_repository_backup(project_dir=str(source), source_id="source", env=repository_env, local_only=True)
        runtime.run_repository_backup(project_dir=str(source), source_id="source", env=repository_env, local_only=True)
    assert capture.call_count == save.call_count == 2
