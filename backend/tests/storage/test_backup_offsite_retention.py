"""Persistent catchup evidence survives local record retention and supersession."""

from __future__ import annotations

from collections.abc import Generator
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


@pytest.mark.parametrize("new_status", [None, "published", "up_to_date", "skipped"])
def test_latest_completed_publication_supersedes_older_failure(catalogue, new_status):
    old = catalogue["create"](publication="failed")
    catalogue["create"](publication=new_status)
    selected = [row["id"] for row in backups.get_pending_backup_publications() if row["source_id"] == catalogue["source"]]
    assert selected == []
    assert backups.get_backup(old) is not None


@pytest.mark.parametrize("publication", ["failed", "pending"])
def test_publication_selector_retries_only_latest_completed_record(catalogue, publication):
    catalogue["create"](publication="failed")
    latest = catalogue["create"](publication=publication)
    catalogue["create"](status="failed", publication="failed")
    selected = [row["id"] for row in backups.get_pending_backup_publications() if row["source_id"] == catalogue["source"]]
    assert selected == [latest]


def test_publication_selector_excludes_disabled_source(catalogue):
    catalogue["create"](publication="failed")
    backups.update_source(catalogue["source"], enabled=False)
    assert not any(row["source_id"] == catalogue["source"] for row in backups.get_pending_backup_publications())


def test_publication_latest_point_follows_completion_not_queue_creation_order(catalogue):
    queued_first = catalogue["create"](publication="failed")
    catalogue["create"](publication="published")
    # A previously queued capture can complete after a later-created point.
    backups.update_backup_status(queued_first, "completed")
    selected = [row["id"] for row in backups.get_pending_backup_publications() if row["source_id"] == catalogue["source"]]
    assert selected == [queued_first]
