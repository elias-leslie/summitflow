"""The existing drain catches up retained copies after an outage."""

from __future__ import annotations

import hashlib
import sys
from contextlib import contextmanager, nullcontext
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest.mock import Mock

import pytest


def record(backup_id="archive-1", source_id="source", *, offsite="failed", publication=None):
    verification = {"verified": True, "offsite": {"status": offsite}}
    if publication:
        verification["publication"] = {"status": publication, "reason": "offline"}
    return {"id": backup_id, "source_id": source_id, "status": "completed",
            "name": backup_id + ".tar.gz.age", "location": "/retained/" + backup_id + ".tar.gz.age",
            "verification_json": verification, "storage_backend_id": "native-local"}


@pytest.fixture
def queue(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    from app.tasks import backup_drain as drain

    for key in ("BACKUP_OFFSITE_GIO_URI", "BACKUP_OFFSITE_TRANSPORT"):
        monkeypatch.delenv(key, raising=False)
    state: dict[str, Any] = {"offsite": [], "legacy": [], "publication": [], "sync": [], "publish": [],
                             "archive_calls": [], "busy": set(), "outcomes": {}, "publish_outcomes": {},
                             "merges": []}
    monkeypatch.setattr(drain.backup_store, "get_pending_upload_backups", lambda: state["legacy"])
    monkeypatch.setattr(drain.backup_store, "get_pending_native_offsite_backups", lambda: state["offsite"])
    monkeypatch.setattr(drain, "build_storage_env", lambda *_args: {"BACKUP_OFFSITE_GIO_URI": "google-drive://fixture/root"})
    monkeypatch.setattr(drain, "has_active_backup_lease", lambda source: source in state["busy"])
    monkeypatch.setattr(drain.backup_store, "get_source", lambda source: {
        "id": source, "path": str(tmp_path), "enabled": True, "source_type": "project",
    })
    monkeypatch.setattr(drain.backup_store, "get_latest_backup", lambda *, source_id: next(
        (item for item in reversed(state["publication"]) if item["source_id"] == source_id), None,
    ))

    def drain_archives(*, dry_run: bool):
        state["archive_calls"].append(dry_run)
        return {"status": "dry_run" if dry_run else "success", "pending_before": 0,
                "backups": [], "uploaded": 0, "failed": 0, "remaining": 0, "failures": []}

    def sync(backup_id):
        state["sync"].append(backup_id)
        outcome = state["outcomes"].get(backup_id, "verified")
        if isinstance(outcome, Exception):
            raise outcome
        return {"verification_json": {"offsite": {"status": outcome, "error": "offline"}}}

    def publish(source, *, retained=None):
        state["publish"].append(source["id"])
        outcome = state["publish_outcomes"].get(source["id"], "published")
        if isinstance(outcome, Exception):
            raise outcome
        return {"status": outcome, "reason": "push_unavailable" if outcome in {"failed", "pending"} else "published",
                "backup_can_continue": True, "attempted": True, "source_id": source["id"]}

    def merge(backup_id, update, **_kwargs):
        state["merges"].append((backup_id, update))
        return {"id": backup_id, "verification_json": update}

    monkeypatch.setattr(drain, "drain_pending_archives", drain_archives)
    monkeypatch.setattr(drain, "sync_backup_offsite", sync)
    monkeypatch.setattr(drain.backup_store, "merge_backup_verification_json", merge)
    publication_module = ModuleType("app.tasks.backup_publish")
    monkeypatch.setattr(publication_module, "publish_source_before_backup", publish, raising=False)
    monkeypatch.setitem(sys.modules, "app.tasks.backup_publish", publication_module)
    return drain, state


def test_native_only_backlog_is_retried_without_smb_reconciliation(queue, monkeypatch):
    drain, state = queue
    state["offsite"] = [record()]
    promote = Mock(side_effect=AssertionError("Native local archive must remain completed"))
    monkeypatch.setattr(drain.backup_store, "promote_pending_upload", promote)
    result = drain.drain_pending_backups()
    assert state["sync"] == ["archive-1"]
    assert state["archive_calls"] == [True]
    assert result["status"] == "success"
    assert result["offsite_verified"] == 1
    assert result["remaining"] == 0
    promote.assert_not_called()


@pytest.mark.parametrize("outcome", ["failed", RuntimeError("offline")])
def test_failed_copy_does_not_block_another_source(queue, outcome):
    drain, state = queue
    state["offsite"] = [record("first", "first-source"), record("second", "second-source")]
    state["outcomes"]["first"] = outcome
    result = drain.drain_pending_backups()
    assert state["sync"] == ["first", "second"]
    assert result["status"] == "partial"
    assert result["offsite_verified"] == 1
    assert result["offsite_failed"] == result["offsite_remaining"] == 1


@pytest.mark.parametrize("verification", [None, {"offsite": "invalid-metadata"}])
def test_malformed_retry_evidence_fails_without_blocking_next_source(queue, monkeypatch, verification):
    drain, state = queue
    state["offsite"] = [record("first", "first-source"), record("second", "second-source")]
    sync = Mock(side_effect=[{"verification_json": verification}, {"verification_json": {"offsite": {"status": "verified"}}}])
    monkeypatch.setattr(drain, "sync_backup_offsite", sync)
    result = drain.drain_pending_backups()
    assert sync.call_count == 2
    assert result["status"] == "partial"
    assert result["offsite_failed"] == result["offsite_verified"] == 1
    assert result["offsite_remaining"] == 1


def test_active_source_is_skipped_and_another_source_retries(queue):
    drain, state = queue
    state["offsite"] = [record("first", "first-source"), record("second", "second-source")]
    state["busy"].add("first-source")
    result = drain.drain_pending_backups()
    assert state["sync"] == ["second"]
    assert result["offsite_skipped"] == 1
    assert result["offsite_remaining"] == 1


@pytest.mark.parametrize("failure", [None, ValueError("Recorded backend disabled")])
def test_unconfigured_or_disabled_route_does_not_erase_existing_failure(queue, monkeypatch, failure):
    drain, state = queue
    retained = record()
    state["offsite"] = [retained]
    build = Mock(return_value={}, side_effect=failure)
    monkeypatch.setattr(drain, "build_storage_env", build)
    result = drain.drain_pending_backups()
    assert not state["sync"]
    assert result["offsite_skipped"] == 1
    assert retained["verification_json"]["offsite"]["status"] == "failed"
    assert not state["merges"]
    build.assert_called_once_with("source", "native-local")


def test_dry_run_is_read_only_for_all_queues(queue):
    drain, state = queue
    retained = record(publication="failed")
    state["offsite"] = [retained]
    state["publication"] = [retained]
    result = drain.drain_pending_backups(dry_run=True)
    assert result["status"] == "dry_run"
    assert result["pending_before"] == 1
    assert result["offsite_backups"][0]["id"] == "archive-1"
    assert not state["sync"] and not state["publish"] and not state["merges"]
    assert state["archive_calls"] == [True]


def test_restic_is_excluded_from_native_sync_and_legacy_promotion(queue, monkeypatch):
    drain, state = queue
    repository = record()
    repository["status"] = "completed_pending_upload"
    repository["verification_json"]["format"] = "restic-v1"
    state["legacy"] = state["offsite"] = [repository]
    promote = Mock()
    monkeypatch.setattr(drain.backup_store, "promote_pending_upload", promote)
    result = drain.drain_pending_backups()
    assert not state["sync"]
    assert result["offsite_pending_before"] == 0
    assert drain._reconcile_pending_records([repository]) == 0
    promote.assert_not_called()


def test_smb_unavailability_does_not_block_native_copy(queue, monkeypatch):
    drain, state = queue
    state["offsite"] = [record()]

    def archives(*, dry_run):
        if dry_run:
            return {"status": "dry_run", "pending_before": 1, "backups": []}
        raise RuntimeError("SMB offline")

    monkeypatch.setattr(drain, "drain_pending_archives", archives)
    result = drain.drain_pending_backups()
    assert state["sync"] == ["archive-1"]
    assert result["status"] == "partial"
    assert result["offsite_verified"] == 1
    assert result["remaining"] == 1


@pytest.mark.parametrize("changed", [False, True])
def test_auto_retry_enters_existing_lease_and_checksum_guard(queue, tmp_path, monkeypatch, changed):
    from app.tasks import backup_executor as executor

    drain, state = queue
    retained = record()
    archive = tmp_path / retained["name"]
    archive.write_bytes(b"exact retained ciphertext")
    retained["location"] = str(archive)
    retained["checksum"] = "sha256:" + hashlib.sha256(archive.read_bytes()).hexdigest()
    state["offsite"] = [retained]
    if changed:
        archive.write_bytes(b"changed ciphertext")
    events = []

    @contextmanager
    def lease(source_id, token):
        events.append(("lease", source_id, token))
        try:
            yield
        finally:
            events.append(("released", source_id, token))

    remote = Mock(return_value={"status": "verified"})
    monkeypatch.setattr(drain, "sync_backup_offsite", executor.sync_backup_offsite)
    monkeypatch.setattr(executor.backup_store, "get_backup", lambda _: retained)
    monkeypatch.setattr(executor, "acquire_backup_lock", lambda _: "owner")
    monkeypatch.setattr(executor, "maintain_backup_lock", lease)
    monkeypatch.setattr(executor, "bind_backup_activity", lambda *_args: nullcontext())
    monkeypatch.setattr(executor, "current_activity", lambda: None)
    monkeypatch.setattr(executor, "build_storage_env", lambda *_args: {})
    monkeypatch.setattr(executor, "replicate_completed_archive", remote)
    result = drain.drain_pending_backups()
    assert events[0] == ("lease", "source", "owner")
    assert events[-1] == ("released", "source", "owner")
    if changed:
        assert result["offsite_failed"] == 1
        remote.assert_not_called()
        assert not state["merges"]
    else:
        assert result["offsite_verified"] == 1
        remote.assert_called_once()
        assert remote.call_args.kwargs["retry"] is True
        assert remote.call_args.args[0] == archive
        assert archive.read_bytes() == b"exact retained ciphertext"


def test_retained_publication_is_never_retried_or_counted_as_backup_work(queue):
    drain, state = queue
    retained = record(offsite="verified", publication="failed")
    state["publication"] = [retained]
    result = drain.drain_pending_backups()
    assert result["remaining"] == 0
    assert not state["publish"] and not state["merges"]
    assert retained["verification_json"]["publication"]["status"] == "failed"


def test_offsite_copy_retries_while_publication_history_stays_unchanged(queue):
    drain, state = queue
    retained = record(offsite="failed", publication="pending")
    state["offsite"] = state["publication"] = [retained]
    result = drain.drain_pending_backups()
    assert result["offsite_verified"] == 1
    assert not state["publish"] and not state["merges"]
    assert retained["verification_json"]["publication"]["status"] == "pending"
