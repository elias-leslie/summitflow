"""Persistent catchup evidence survives local record retention and supersession."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from app.storage import backups
from app.storage.connection import get_connection


@pytest.fixture
def catalogue(project_id: str) -> Generator[dict[str, Any]]:
    source_id = "test-offsite-catchup-" + uuid4().hex
    backups.create_source(source_id, "Catchup fixture", "/tmp/retained-fixture", project_id=project_id)
    backups.update_source(source_id, enabled=True)
    ids: list[str] = []

    def create(*, status="completed", offsite=None, publication=None, restic=False):
        backup = backups.create_backup_record(project_id, source_id=source_id)
        ids.append(backup["id"])
        verification: dict[str, Any] = {"verified": True}
        if offsite is not None:
            verification["offsite"] = {"status": offsite}
        if publication is not None:
            verification["publication"] = {"status": publication, "reason": "offline"}
        if restic:
            verification["format"] = "restic-v1"
        backups.update_backup_status(backup["id"], status, verification_json=verification)
        return backup["id"]

    def age(backup_ids: list[str]):
        # Isolated test DB only, following existing storage aging fixtures.
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("UPDATE backups SET created_at = NOW() - INTERVAL '90 days' WHERE id = ANY(%s)", (backup_ids,))
            conn.commit()

    yield {"source": source_id, "create": create, "age": age}
    for backup_id in ids:
        backups.delete_backup_record(backup_id)
    backups.delete_source(source_id)


@pytest.mark.parametrize("offsite", ["pending", "failed"])
def test_completed_native_copy_waiting_for_offsite_never_expires(catalogue, offsite):
    backup_id = catalogue["create"](offsite=offsite)
    catalogue["age"]([backup_id])
    backups.cleanup_expired_backup_records(min_keep=0)
    retained = backups.get_backup(backup_id)
    assert retained is not None
    assert retained["status"] == "completed"
    assert retained["verification_json"]["offsite"]["status"] == offsite


@pytest.mark.parametrize("offsite", ["pending", "failed"])
def test_failed_row_with_recorded_pending_copy_survives_stale_cleanup(catalogue, offsite):
    backup_id = catalogue["create"](status="failed", offsite=offsite)
    catalogue["age"]([backup_id])
    backups.cleanup_stale_backup_records()
    assert backups.get_backup(backup_id) is not None


@pytest.mark.parametrize("offsite", [None, "unconfigured", "verified"])
def test_nonpending_native_copies_are_not_retained_forever(catalogue, offsite):
    completed = catalogue["create"](offsite=offsite)
    failed = catalogue["create"](status="failed", offsite=offsite)
    catalogue["age"]([completed, failed])
    backups.cleanup_expired_backup_records(min_keep=0)
    backups.cleanup_stale_backup_records()
    assert backups.get_backup(completed) is None
    assert backups.get_backup(failed) is None


@pytest.mark.parametrize("offsite", ["pending", "failed"])
def test_offsite_backlog_does_not_displace_minimum_verified_local_points(catalogue, offsite):
    stable = [catalogue["create"](offsite="verified") for _ in range(3)]
    catalogue["age"](stable)
    for _ in range(4):
        catalogue["create"](offsite=offsite)
    backups.cleanup_expired_backup_records(min_keep=3)
    assert all(backups.get_backup(backup_id) is not None for backup_id in stable)


def test_native_retry_selector_keeps_every_outstanding_archive_and_excludes_restic(catalogue):
    expected = [catalogue["create"](offsite="failed"), catalogue["create"](offsite="pending")]
    excluded = [catalogue["create"](offsite="verified"), catalogue["create"](offsite="unconfigured"),
                catalogue["create"](), catalogue["create"](offsite="failed", restic=True),
                catalogue["create"](status="failed", offsite="failed")]
    selected = [row["id"] for row in backups.get_pending_native_offsite_backups() if row["source_id"] == catalogue["source"]]
    assert selected == expected
    assert not set(excluded) & set(selected)


def test_expiry_failed_unlink_preserves_catalogue_then_success_removes_it(catalogue, tmp_path, monkeypatch):
    root = tmp_path / "source"
    archive = root / "backups" / "fixture.tar.gz.age"
    archive.parent.mkdir(parents=True)
    archive.write_bytes(b"synthetic-encrypted-artifact")
    backups.update_source(catalogue["source"], path=str(root))
    backup_id = catalogue["create"](offsite="verified")
    backups.update_backup_status(backup_id, "completed", location=str(archive))
    catalogue["age"]([backup_id])
    unlink = Path.unlink
    def denied(path, *args, **kwargs):
        if path == archive:
            raise PermissionError("synthetic failure")
        return unlink(path, *args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(Path, "unlink", denied)
        assert backups.cleanup_expired_backup_records(min_keep=0) == 0
    retained = backups.get_backup(backup_id)
    assert retained is not None
    assert retained["verification_json"]["offsite"]["status"] == "verified"
    assert archive.exists()
    assert backups.cleanup_expired_backup_records(min_keep=0) == 1
    assert not archive.exists()
    assert backups.get_backup(backup_id) is None


def test_expiry_refuses_unbounded_or_remote_artifact(catalogue, tmp_path):
    archive = tmp_path / "unowned.tar.gz.age"
    archive.write_bytes(b"retained evidence")
    ids = [catalogue["create"](offsite="verified") for _ in range(2)]
    for backup_id, location in zip(ids, [str(archive), "//remote/retained.tar.gz.age"], strict=True):
        backups.update_backup_status(backup_id, "completed", location=location)
    catalogue["age"](ids)
    assert backups.cleanup_expired_backup_records(min_keep=0) == 0
    assert archive.exists()
    assert all(backups.get_backup(backup_id) for backup_id in ids)


def test_frequency_change_recalculates_due_without_changing_retention(catalogue):
    backups.update_source(catalogue["source"], retention_days=37)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE backup_sources SET last_run_at = NOW() - INTERVAL '5 hours', next_run_at = NOW() + INTERVAL '25 days' WHERE id = %s", (catalogue["source"],))
        conn.commit()
    # This integration also runs on the existing shared test DB before rollout.
    # Four-hour admission itself is covered by the isolated migration/API tests.
    updated = backups.update_source(catalogue["source"], frequency="hourly")
    assert updated is not None
    from datetime import datetime
    last = datetime.fromisoformat(updated["last_run_at"])
    due = datetime.fromisoformat(updated["next_run_at"])
    assert (due - last).total_seconds() == 3600
    assert updated["retention_days"] == 37
