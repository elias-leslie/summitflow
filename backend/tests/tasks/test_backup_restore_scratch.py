"""Actual restore staging routes with synthetic payloads and no repository I/O."""

from __future__ import annotations

import os
import shutil
import stat
import tarfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.tasks import backup_repository_runtime as runtime
from app.tasks.backup_activity import BackupCancelled
from app.utils import transient_scratch as scratch


@pytest.fixture
def staging(tmp_path, monkeypatch):
    root = tmp_path / "scratch"
    root.mkdir(mode=0o700)
    monkeypatch.setattr(scratch, "SCRATCH_ROOT", root)
    monkeypatch.setattr(Path, "is_mount", lambda path: path == root)
    usage = shutil.disk_usage(tmp_path)
    monkeypatch.setattr(scratch.shutil, "disk_usage", lambda _path: usage._replace(free=100 * 1024**3))
    return root


@pytest.mark.parametrize("failure", [None, "restore", "consumer"])
def test_repository_materialization_stages_real_payload_and_archive_on_scratch(
    staging, monkeypatch, failure,
):
    backup = {"source_id": "codex-config", "total_bytes": 16, "verification_json": {
        "snapshot_id": "a" * 64, "logical_bytes": 32,
    }}
    adapter = MagicMock()
    jobs = []

    def restore(_snapshot, target, **_kwargs):
        jobs.append(target.parent)
        assert target.parent.parent == staging / f"st-restores-{os.getuid()}"
        assert stat.S_IMODE(target.stat().st_mode) == 0o700
        if failure == "restore":
            raise BackupCancelled("fixture cancellation")
        payload = target / "payload"
        payload.mkdir(mode=0o700)
        (payload / "saved").write_bytes(b"fixture configuration")
        return {"payload_root": str(payload)}

    adapter.restore.side_effect = restore
    monkeypatch.setattr(runtime, "_backup_environment", lambda _backup: {})
    monkeypatch.setattr(runtime.ResticConfig, "from_env", lambda _env: MagicMock())
    monkeypatch.setattr(runtime, "ResticAdapter", lambda _config: adapter)
    monkeypatch.setattr(runtime, "_approved_key_directory", lambda _config: None)
    monkeypatch.setattr(runtime, "_assert_repository_identity", lambda *_args, **_kwargs: None)
    requirements = []
    original = scratch.ensure_scratch_capacity

    def capacity(path, required):
        requirements.append(required)
        original(path, required)

    monkeypatch.setattr(scratch, "ensure_scratch_capacity", capacity)
    monkeypatch.setattr(runtime, "ensure_scratch_capacity", capacity)

    def consume():
        with runtime.materialize_repository_archive(backup) as archive:
            assert archive.parent == jobs[0]
            assert stat.S_IMODE(archive.stat().st_mode) == 0o600
            with tarfile.open(archive, "r:gz") as contents:
                assert contents.getmember("payload/saved").size == len(b"fixture configuration")
            if failure == "consumer":
                raise ValueError("fixture consumer failure")

    if failure:
        with pytest.raises(BackupCancelled if failure == "restore" else ValueError):
            consume()
    else:
        consume()
    assert requirements[0] == 64
    if failure != "restore":
        assert requirements[1:] == [len(b"fixture configuration"), len(b"fixture configuration"), 0]
    assert not jobs[0].exists()


@pytest.mark.parametrize("failure", ["capacity", "creation"])
def test_critical_scratch_refusal_records_failed_attempt_without_erasing_success(staging, monkeypatch, failure):
    backup = {"id": "fixture-point", "source_id": "codex-config", "storage_backend_id": "fixture", "total_bytes": 100,
              "verification_json": {"format": "restic-v1", "snapshot_id": "a" * 64,
                                    "remote_snapshot_id": "b" * 64, "offsite": {"status": "verified"}}}
    monkeypatch.setattr(runtime.backup_store, "list_sources", lambda: [{"id": "codex-config", "enabled": True}])
    monkeypatch.setattr(runtime.backup_store, "list_backups", lambda **_kwargs: ([backup], 1))
    usage = shutil.disk_usage(staging)
    monkeypatch.setenv("SF_HOST_RETENTION_PRESSURE_MIN_FREE_GB", "25")
    free = 25 * 1024**3 + 399 if failure == "capacity" else 100 * 1024**3
    monkeypatch.setattr(scratch.shutil, "disk_usage", lambda _path: usage._replace(free=free))
    if failure == "creation":
        monkeypatch.setattr(scratch.tempfile, "TemporaryDirectory", MagicMock(side_effect=OSError("fixture creation failure")))
    success = {"status": "verified", "verified_at": "2026-01-01T00:00:00+00:00"}
    maintenance = {"critical_restore_success": success.copy()}
    materialize = MagicMock()
    persisted = MagicMock()
    monkeypatch.setattr(runtime, "materialize_repository_archive", materialize)
    result = runtime._weekly_critical_restore({"BACKUP_STORAGE_BACKEND_ID": "fixture"}, maintenance, persist=persisted)
    assert result["status"] == "failed"
    assert ("400 additional known bytes" if failure == "capacity" else "fixture creation failure") in result["error"]
    assert maintenance["critical_restore_attempt"]["status"] == "failed"
    assert maintenance["critical_restore_success"] == success
    materialize.assert_not_called()
    assert persisted.call_count == 2
