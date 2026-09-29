"""Tests for the backup storage module."""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC
from typing import Any

import pytest

from app.storage import backups
from app.storage.connection import get_connection


@pytest.fixture
def conn() -> Generator[Any]:
    """Database connection fixture."""
    with get_connection() as connection:
        yield connection


@pytest.fixture
def cleanup_project(conn: Any) -> Generator[str]:
    """Fixture to clean up test project data after tests."""
    project_id = "test-backup-project"

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO projects (id, name, base_url, root_path)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (id) DO NOTHING
            """,
            (project_id, "Test Backup Project", "http://localhost", "/tmp/test-backup-project"),
        )
        # Create a backup source so that backups can reference it via source_id FK
        cur.execute(
            """
            INSERT INTO backup_sources (id, name, path, source_type, project_id)
            VALUES (%s, %s, %s, 'project', %s)
            ON CONFLICT (id) DO NOTHING
            """,
            (project_id, "Test Backup Project", "/tmp/test-backup-project", project_id),
        )
        conn.commit()

    yield project_id

    with conn.cursor() as cur:
        cur.execute("DELETE FROM backups WHERE project_id = %s", (project_id,))
        cur.execute("DELETE FROM backup_sources WHERE id = %s", (project_id,))
        cur.execute("DELETE FROM projects WHERE id = %s", (project_id,))
        conn.commit()


class TestBackupCRUD:
    """Tests for backup CRUD operations."""

    def test_create_backup_record(self, cleanup_project: str) -> None:
        """Create backup record returns valid record."""
        backup = backups.create_backup_record(
            project_id=cleanup_project,
            backup_type="manual",
            note="Test backup",
        )

        assert backup["id"].startswith("bkp-")
        assert backup["project_id"] == cleanup_project
        assert backup["status"] == "pending"
        assert backup["backup_type"] == "manual"
        assert backup["note"] == "Test backup"
        assert backup["created_at"] is not None

    def test_get_backup(self, cleanup_project: str) -> None:
        """Get backup by ID returns correct record."""
        created = backups.create_backup_record(cleanup_project)
        fetched = backups.get_backup(created["id"])

        assert fetched is not None
        assert fetched["id"] == created["id"]
        assert fetched["project_id"] == cleanup_project

    def test_get_backup_not_found(self) -> None:
        """Get nonexistent backup returns None."""
        result = backups.get_backup("bkp-nonexistent")
        assert result is None

    def test_list_backups_empty(self, cleanup_project: str) -> None:
        """List backups returns empty for new project."""
        result, total = backups.list_backups(project_id=cleanup_project)
        assert result == []
        assert total == 0

    def test_list_backups_with_data(self, cleanup_project: str) -> None:
        """List backups returns created records."""
        backups.create_backup_record(cleanup_project, note="First")
        backups.create_backup_record(cleanup_project, note="Second")

        result, total = backups.list_backups(project_id=cleanup_project)
        assert len(result) == 2
        assert total == 2

    def test_list_backups_filter_by_status(self, cleanup_project: str) -> None:
        """List backups filters by status."""
        b1 = backups.create_backup_record(cleanup_project)
        backups.create_backup_record(cleanup_project)
        backups.update_backup_status(b1["id"], "completed")

        result, _total = backups.list_backups(project_id=cleanup_project, status="completed")
        assert len(result) == 1
        assert result[0]["id"] == b1["id"]

    def test_update_backup_status(self, cleanup_project: str) -> None:
        """Update backup status changes status and timestamps."""
        backup = backups.create_backup_record(cleanup_project)

        updated = backups.update_backup_status(
            backup["id"],
            status="running",
        )
        assert updated is not None
        assert updated["status"] == "running"
        assert updated["started_at"] is not None

        completed = backups.update_backup_status(
            backup["id"],
            status="completed",
            size_bytes=1024000,
            db_size_bytes=512000,
            files_size_bytes=512000,
            location="/backups/test",
        )
        assert completed is not None
        assert completed["status"] == "completed"
        assert completed["completed_at"] is not None
        assert completed["size_bytes"] == 1024000
        assert completed["location"] == "/backups/test"

    def test_update_backup_status_failed(self, cleanup_project: str) -> None:
        """Update backup to failed status includes error message."""
        backup = backups.create_backup_record(cleanup_project)

        failed = backups.update_backup_status(
            backup["id"],
            status="failed",
            error_message="Disk full",
        )
        assert failed is not None
        assert failed["status"] == "failed"
        assert failed["error_message"] == "Disk full"

    def test_merge_backup_verification_json(self, cleanup_project: str) -> None:
        """Merging verification metadata preserves existing fields."""
        backup = backups.create_backup_record(cleanup_project)
        backups.update_backup_status(
            backup["id"],
            status="completed",
            verification_json={"has_db": True, "tree": {"files": 1}},
        )

        updated = backups.merge_backup_verification_json(
            backup["id"],
            {
                "testbed_baseline": {
                    "snapshot_id": "snap-123",
                    "git": {"branch": "main"},
                }
            },
        )

        assert updated is not None
        assert updated["verification_json"]["has_db"] is True
        assert updated["verification_json"]["tree"] == {"files": 1}
        assert updated["verification_json"]["testbed_baseline"]["snapshot_id"] == "snap-123"

    def test_delete_backup_record(self, cleanup_project: str) -> None:
        """Delete backup removes record."""
        backup = backups.create_backup_record(cleanup_project)
        assert backups.get_backup(backup["id"]) is not None

        deleted = backups.delete_backup_record(backup["id"])
        assert deleted
        assert backups.get_backup(backup["id"]) is None

    def test_delete_backup_not_found(self) -> None:
        """Delete nonexistent backup returns False."""
        result = backups.delete_backup_record("bkp-nonexistent")
        assert not result

    def test_get_latest_backup_filters_by_verification_key(self, cleanup_project: str) -> None:
        """Latest backup lookup can require a verification_json marker."""
        manual = backups.create_backup_record(cleanup_project, backup_type="manual")
        baseline = backups.create_backup_record(cleanup_project, backup_type="manual")

        backups.update_backup_status(manual["id"], status="completed")
        backups.update_backup_status(
            baseline["id"],
            status="completed",
            verification_json={"testbed_baseline": {"snapshot_id": "snap-123"}},
        )

        latest = backups.get_latest_backup(
            project_id=cleanup_project,
            verification_key="testbed_baseline",
        )

        assert latest is not None
        assert latest["id"] == baseline["id"]


class TestSourceCRUD:
    """Tests for backup source CRUD operations."""

    def test_get_source_not_found(self) -> None:
        """Get source returns None when not found."""
        result = backups.get_source("nonexistent-source")
        assert result is None

    def test_get_source(self, cleanup_project: str) -> None:
        """Get source returns existing source (created by fixture)."""
        source = backups.get_source(cleanup_project)
        assert source is not None
        assert source["id"] == cleanup_project
        assert source["source_type"] == "project"

    def test_update_source(self, cleanup_project: str) -> None:
        """Update source updates allowed fields."""
        updated = backups.update_source(
            cleanup_project,
            enabled=True,
            frequency="weekly",
            retention_days=10,
        )

        assert updated is not None
        assert updated["enabled"]
        assert updated["frequency"] == "weekly"
        assert updated["retention_days"] == 10

    def test_update_source_last_run(self, cleanup_project: str) -> None:
        """Update source last run updates timestamps."""
        from datetime import datetime, timedelta

        next_run = datetime.now(UTC) + timedelta(days=1)

        result = backups.update_source_last_run(cleanup_project, next_run)
        assert result

        source = backups.get_source(cleanup_project)
        assert source is not None
        assert source["last_run_at"] is not None
        assert source["next_run_at"] is not None

    def test_list_due_sources(self, conn: Any, cleanup_project: str) -> None:
        """List due sources returns sources ready to run."""
        # Enable the source so it qualifies as due
        backups.update_source(cleanup_project, enabled=True)

        with conn.cursor() as cur:
            cur.execute(
                "UPDATE backup_sources SET next_run_at = NOW() - INTERVAL '1 hour' WHERE id = %s",
                (cleanup_project,),
            )
            conn.commit()

        due = backups.list_due_sources()
        source_ids = [s["id"] for s in due]
        assert cleanup_project in source_ids


class TestStorageSummary:
    """Tests for storage summary functions."""

    def test_get_storage_summary_empty(self, cleanup_project: str) -> None:
        """Storage summary returns zeros for empty project."""
        summary = backups.get_storage_summary(cleanup_project)
        assert summary["total_count"] == 0
        assert summary["total_bytes"] == 0

    def test_get_storage_summary_with_data(self, cleanup_project: str) -> None:
        """Storage summary returns correct counts and sizes."""
        b1 = backups.create_backup_record(cleanup_project)
        b2 = backups.create_backup_record(cleanup_project)

        backups.update_backup_status(b1["id"], "completed", size_bytes=1000)
        backups.update_backup_status(b2["id"], "completed", size_bytes=2000)

        summary = backups.get_storage_summary(cleanup_project)
        assert summary["total_count"] == 2
        assert summary["total_bytes"] == 3000
        assert summary["by_status"]["completed"] == 2

    def test_get_latest_backup(self, cleanup_project: str) -> None:
        """Get latest backup returns most recent completed."""
        b1 = backups.create_backup_record(cleanup_project, note="First")
        b2 = backups.create_backup_record(cleanup_project, note="Second")

        backups.update_backup_status(b1["id"], "completed")
        backups.update_backup_status(b2["id"], "completed")

        latest = backups.get_latest_backup(cleanup_project)
        assert latest is not None
        assert latest["note"] == "Second"

    def test_get_latest_backup_no_completed(self, cleanup_project: str) -> None:
        """Get latest backup returns None when no completed backups."""
        backups.create_backup_record(cleanup_project)

        latest = backups.get_latest_backup(cleanup_project)
        assert latest is None


class TestCleanupExpiredRecords:
    """Tests for cleanup_expired_backup_records."""

    @pytest.mark.parametrize("min_keep", [0, 3])
    def test_old_pending_uploads_never_expire(self, conn: Any, cleanup_project: str, min_keep: int) -> None:
        pending = []
        for _ in range(6):
            rec = backups.create_backup_record(cleanup_project)
            backups.update_backup_status(rec["id"], "completed_pending_upload")
            pending.append(rec["id"])
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE backups SET created_at = NOW() - INTERVAL '90 days' WHERE project_id = %s",
                (cleanup_project,),
            )
            conn.commit()
        for _ in range(3):
            rec = backups.create_backup_record(cleanup_project)
            backups.update_backup_status(rec["id"], "completed")

        assert backups.cleanup_expired_backup_records(min_keep=min_keep) == 0
        assert all(backups.get_backup(backup_id) is not None for backup_id in pending)

    @pytest.mark.parametrize("status,verification", [
        ("completed_pending_upload", {}),
        ("completed", {"activity": {"active": True}}),
        ("completed", {"offsite": {"status": "pending"}}),
        ("completed", {"format": "restic-v1"}),
    ])
    def test_protected_copies_do_not_displace_completed_minimum(
        self, conn: Any, cleanup_project: str, status: str, verification: dict[str, Any],
    ) -> None:
        stable_ids = []
        for _ in range(3):
            rec = backups.create_backup_record(cleanup_project)
            backups.update_backup_status(rec["id"], "completed")
            stable_ids.append(rec["id"])
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE backups SET created_at = NOW() - INTERVAL '90 days' WHERE project_id = %s",
                (cleanup_project,),
            )
            conn.commit()
        for _ in range(3):
            rec = backups.create_backup_record(cleanup_project)
            backups.update_backup_status(rec["id"], status, verification_json=verification)

        assert backups.cleanup_expired_backup_records(min_keep=3) == 0
        assert all(backups.get_backup(backup_id) is not None for backup_id in stable_ids)

    def test_old_pending_verification_never_expires(self, conn: Any, cleanup_project: str) -> None:
        rec = backups.create_backup_record(cleanup_project)
        backups.update_backup_status(rec["id"], "completed", verification_json={"offsite": {"status": "pending"}})
        with conn.cursor() as cur:
            cur.execute("UPDATE backups SET created_at = NOW() - INTERVAL '90 days' WHERE id = %s", (rec["id"],))
            conn.commit()

        assert backups.cleanup_expired_backup_records(min_keep=0) == 0
        assert backups.get_backup(rec["id"]) is not None

    def test_legacy_cleanup_never_expires_restic_snapshot_records(self, conn: Any, cleanup_project: str) -> None:
        records = []
        for _ in range(4):
            rec = backups.create_backup_record(cleanup_project)
            backups.update_backup_status(rec["id"], "completed", verification_json={
                "format": "restic-v1", "snapshot_id": "fixture-snapshot",
            })
            records.append(rec["id"])
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE backups SET created_at = NOW() - INTERVAL '90 days' WHERE project_id = %s",
                (cleanup_project,),
            )
            conn.commit()

        assert backups.cleanup_expired_backup_records(min_keep=0) == 0
        assert all(backups.get_backup(backup_id) is not None for backup_id in records)

    def test_cleanup_expired_deletes_old_records(self, conn: Any, cleanup_project: str) -> None:
        """Cleanup deletes completed records older than retention, keeping min per project."""
        # Create 5 completed backups, backdate 4 of them to 20 days ago
        records = []
        for i in range(5):
            rec = backups.create_backup_record(cleanup_project, note=f"Backup {i}")
            backups.update_backup_status(rec["id"], "completed")
            records.append(rec)

        # Backdate 4 oldest records
        with conn.cursor() as cur:
            for rec in records[:4]:
                cur.execute(
                    "UPDATE backups SET created_at = NOW() - INTERVAL '20 days' WHERE id = %s",
                    (rec["id"],),
                )
            conn.commit()

        # Cleanup with retention_days=14, min_keep=3
        deleted = backups.cleanup_expired_backup_records(default_retention_days=14, min_keep=3)

        # Window keeps 3 newest (1 recent + 2 old), deletes remaining 2 old
        assert deleted == 2

        # Verify 3 remain (top 3 by created_at DESC)
        remaining, _total = backups.list_backups(project_id=cleanup_project)
        completed = [r for r in remaining if r["status"] == "completed"]
        assert len(completed) == 3

    def test_cleanup_expired_respects_min_keep(self, conn: Any, cleanup_project: str) -> None:
        """Cleanup never deletes below min_keep per project."""
        # Create 3 completed backups, all old
        records = []
        for i in range(3):
            rec = backups.create_backup_record(cleanup_project, note=f"Old {i}")
            backups.update_backup_status(rec["id"], "completed")
            records.append(rec)

        with conn.cursor() as cur:
            for rec in records:
                cur.execute(
                    "UPDATE backups SET created_at = NOW() - INTERVAL '30 days' WHERE id = %s",
                    (rec["id"],),
                )
            conn.commit()

        # Cleanup with min_keep=3 — should delete nothing
        deleted = backups.cleanup_expired_backup_records(default_retention_days=14, min_keep=3)
        assert deleted == 0

    def test_cleanup_expired_ignores_non_completed(self, conn: Any, cleanup_project: str) -> None:
        """Cleanup only affects completed records, not pending/failed."""
        # Create a pending and a failed backup, both old
        backups.create_backup_record(cleanup_project, note="Pending old")
        failed = backups.create_backup_record(cleanup_project, note="Failed old")
        backups.update_backup_status(failed["id"], "failed")

        with conn.cursor() as cur:
            cur.execute(
                "UPDATE backups SET created_at = NOW() - INTERVAL '30 days' WHERE project_id = %s",
                (cleanup_project,),
            )
            conn.commit()

        deleted = backups.cleanup_expired_backup_records(default_retention_days=14, min_keep=3)
        assert deleted == 0

        # Both records should still exist
        _remaining, total = backups.list_backups(project_id=cleanup_project)
        assert total == 2


class TestFailStaleRunningBackups:
    """Tests for fail_stale_running_backups."""

    def test_active_old_completed_archive_survives_expiry_until_orphan_reconciled(self, conn: Any, cleanup_project: str) -> None:
        old = backups.create_backup_record(cleanup_project)
        backups.update_backup_status(old["id"], "completed", verification_json={"activity": {
            "run_id": "active-run", "active": True, "phase": "upload",
        }})
        for _ in range(3):
            fresh = backups.create_backup_record(cleanup_project)
            backups.update_backup_status(fresh["id"], "completed")
        with conn.cursor() as cur:
            cur.execute("UPDATE backups SET created_at = NOW() - INTERVAL '40 days' WHERE id = %s", (old["id"],))
            conn.commit()
        assert backups.cleanup_expired_backup_records() == 0
        assert backups.fail_stale_running_backups(is_source_active=lambda _: False) == 0
        row = backups.get_backup(old["id"])
        assert row is not None and row["status"] == "completed"
        assert row["verification_json"]["activity"]["active"] is False
        assert row["verification_json"]["activity"]["attention"] is True
        assert backups.cleanup_expired_backup_records() == 1

    def test_same_run_cancel_survives_activity_start_and_local_checkpoint(self, cleanup_project: str) -> None:
        backup = backups.create_backup_record(cleanup_project)
        backup_id = backup["id"]
        backups.merge_backup_verification_json(backup_id, {"activity": {
            "run_id": "run-1", "active": True, "cancel_requested": False,
        }})
        assert backups.request_backup_cancellation(backup_id, "run-1")
        backups.merge_backup_verification_json(backup_id, {"activity": {
            "run_id": "run-1", "phase": "capture", "cancel_requested": False,
        }})
        backups.update_backup_status(backup_id, "completed", verification_json={
            "verified": True, "activity": {"run_id": "run-1", "cancel_requested": False},
        })
        row = backups.get_backup(backup_id)
        assert row is not None
        assert row["verification_json"]["activity"]["cancel_requested"] is True
        backups.merge_backup_verification_json(backup_id, {"activity": {
            "run_id": "run-2", "active": True, "cancel_requested": False,
        }})
        row = backups.get_backup(backup_id)
        assert row is not None
        assert row["verification_json"]["activity"]["cancel_requested"] is False
        assert backups.merge_backup_verification_json(
            backup_id, {"activity": {"active": False}, "offsite": {"status": "failed"}},
            expected_activity_run_id="run-1",
        ) is None
        row = backups.get_backup(backup_id)
        assert row is not None and row["verification_json"]["activity"]["active"] is True

    def test_retention_never_deletes_running_rows_by_age(self, conn: Any, cleanup_project: str) -> None:
        running = backups.create_backup_record(cleanup_project)
        failed = backups.create_backup_record(cleanup_project)
        backups.update_backup_status(running["id"], "running")
        backups.update_backup_status(failed["id"], "failed")
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE backups SET created_at = NOW() - INTERVAL '40 days' WHERE id = ANY(%s)",
                ([running["id"], failed["id"]],),
            )
            conn.commit()
        assert backups.cleanup_stale_backup_records() == 1
        assert backups.get_backup(running["id"]) is not None
        assert backups.get_backup(failed["id"]) is None

    def test_fail_stale_running_backups_marks_old_rows_failed(
        self, conn: Any, cleanup_project: str
    ) -> None:
        """Old running backups should be failed instead of lingering indefinitely."""
        stale = backups.create_backup_record(cleanup_project, note="Stale")
        fresh = backups.create_backup_record(cleanup_project, note="Fresh")

        backups.update_backup_status(stale["id"], "running")
        backups.update_backup_status(fresh["id"], "running")

        with conn.cursor() as cur:
            cur.execute(
                "UPDATE backups SET started_at = NOW() - INTERVAL '2 hours' WHERE id = %s",
                (stale["id"],),
            )
            cur.execute(
                "UPDATE backups SET started_at = NOW() - INTERVAL '10 minutes' WHERE id = %s",
                (fresh["id"],),
            )
            conn.commit()

        failed = backups.fail_stale_running_backups(max_age_minutes=30, is_source_active=lambda _: False)

        stale_row = backups.get_backup(stale["id"])
        fresh_row = backups.get_backup(fresh["id"])

        assert failed == 1
        assert stale_row is not None
        assert stale_row["status"] == "failed"
        assert stale_row["completed_at"] is not None
        assert "no active backup lease" in (stale_row["error_message"] or "")
        assert fresh_row is not None
        assert fresh_row["status"] == "running"

    @pytest.mark.parametrize("lease_state", ["active", "unknown"])
    def test_long_running_backup_is_not_an_orphan_with_active_or_unknown_lease(
        self, conn: Any, cleanup_project: str, lease_state: str,
    ) -> None:
        stale = backups.create_backup_record(cleanup_project)
        backups.update_backup_status(stale["id"], "running")
        with conn.cursor() as cur:
            cur.execute("UPDATE backups SET started_at = NOW() - INTERVAL '2 hours' WHERE id = %s", (stale["id"],))
            conn.commit()

        def is_active(source_id: str) -> bool:
            assert source_id == cleanup_project
            if lease_state == "unknown":
                raise ConnectionError("Redis unavailable")
            return True

        if lease_state == "unknown":
            with pytest.raises(ConnectionError, match="Redis unavailable"):
                backups.fail_stale_running_backups(is_source_active=is_active)
        else:
            assert backups.fail_stale_running_backups(is_source_active=is_active) == 0
        row = backups.get_backup(stale["id"])
        assert row is not None and row["status"] == "running"
