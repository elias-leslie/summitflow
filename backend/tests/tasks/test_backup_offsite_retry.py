"""Retained ciphertext must match its recorded checksum before Drive access."""

from __future__ import annotations

import hashlib
from contextlib import contextmanager, nullcontext
from pathlib import Path
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def retained_archive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from app.tasks import backup_executor as executor

    archive = tmp_path / "source-20260929-120000.tar.gz.age"
    archive.write_bytes(b"recorded encrypted payload")
    backup = {
        "id": "backup", "status": "completed", "source_id": "source",
        "name": archive.name, "location": str(archive),
        "checksum": "sha256:" + hashlib.sha256(archive.read_bytes()).hexdigest(),
        "verification_json": {"offsite": {"status": "verified", "location": "google-drive://fixture/good"}},
    }
    events = []

    @contextmanager
    def lease(source_id, token):
        assert (source_id, token) == ("source", "lease")
        events.append("lease")
        yield
        events.append("released")

    checksum = executor.archive_sha256

    def guarded_checksum(path):
        assert events == ["lease"]
        events.append("checksum")
        return checksum(path)

    remote = MagicMock(return_value={"status": "verified"})
    merge = MagicMock(return_value=None)
    storage_env = MagicMock(return_value={})
    monkeypatch.setattr(executor.backup_store, "get_backup", lambda _: backup)
    monkeypatch.setattr(executor.backup_store, "get_source", lambda _: {"path": str(tmp_path)})
    monkeypatch.setattr(executor.backup_store, "merge_backup_verification_json", merge)
    monkeypatch.setattr(executor, "acquire_backup_lock", lambda _: "lease")
    monkeypatch.setattr(executor, "maintain_backup_lock", lease)
    monkeypatch.setattr(executor, "bind_backup_activity", lambda *_args: nullcontext())
    monkeypatch.setattr(executor, "current_activity", lambda: None)
    monkeypatch.setattr(executor, "archive_sha256", guarded_checksum)
    monkeypatch.setattr(executor, "replicate_completed_archive", remote)
    monkeypatch.setattr(executor, "build_storage_env", storage_env)
    return executor, archive, backup, events, remote, merge, storage_env


@pytest.mark.parametrize("checksum", [None, "", "sha256:" + "0" * 64])
def test_missing_or_mismatching_recorded_checksum_preserves_verified_remote(retained_archive, checksum):
    executor, archive, backup, events, remote, merge, storage_env = retained_archive
    backup["checksum"] = checksum
    before = archive.read_bytes()

    with pytest.raises(RuntimeError, match=r"no recorded checksum|checksum mismatch"):
        executor.sync_backup_offsite("backup")

    assert events[0] == "lease"
    assert archive.read_bytes() == before
    assert backup["verification_json"]["offsite"]["status"] == "verified"
    remote.assert_not_called()
    merge.assert_not_called()
    storage_env.assert_not_called()


def test_changed_local_ciphertext_cannot_replace_recorded_remote(retained_archive):
    executor, archive, _backup, _events, remote, merge, storage_env = retained_archive
    archive.write_bytes(b"changed encrypted payload")

    with pytest.raises(RuntimeError, match="checksum mismatch"):
        executor.sync_backup_offsite("backup")

    remote.assert_not_called()
    merge.assert_not_called()
    storage_env.assert_not_called()


def test_valid_recorded_ciphertext_is_checked_under_lease_before_replication(retained_archive):
    executor, archive, _backup, events, remote, merge, _storage_env = retained_archive

    assert executor.sync_backup_offsite("backup")["verification_json"]["offsite"]["status"] == "verified"
    assert events == ["lease", "checksum", "released"]
    remote.assert_called_once_with(
        archive, source_id="source", local_dir=archive.parent, env={},
        retention_days=14, retry=True, on_progress=None,
    )
    assert merge.call_count == 2
