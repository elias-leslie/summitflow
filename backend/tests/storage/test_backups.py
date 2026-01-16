"""Tests for the backup storage module."""

from datetime import UTC

import pytest

from app.storage import backups
from app.storage.connection import get_connection


@pytest.fixture
def conn():
    """Database connection fixture."""
    with get_connection() as connection:
        yield connection


@pytest.fixture
def cleanup_project(conn):
    """Fixture to clean up test project data after tests."""
    project_id = "test-backup-project"

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO projects (id, name, base_url)
            VALUES (%s, %s, %s)
            ON CONFLICT (id) DO NOTHING
            """,
            (project_id, "Test Backup Project", "http://localhost"),
        )
        conn.commit()

    yield project_id

    with conn.cursor() as cur:
        cur.execute("DELETE FROM backups WHERE project_id = %s", (project_id,))
        cur.execute("DELETE FROM backup_schedules WHERE project_id = %s", (project_id,))
        cur.execute("DELETE FROM projects WHERE id = %s", (project_id,))
        conn.commit()


class TestBackupCRUD:
    """Tests for backup CRUD operations."""

    def test_create_backup_record(self, cleanup_project):
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

    def test_get_backup(self, cleanup_project):
        """Get backup by ID returns correct record."""
        created = backups.create_backup_record(cleanup_project)
        fetched = backups.get_backup(created["id"])

        assert fetched is not None
        assert fetched["id"] == created["id"]
        assert fetched["project_id"] == cleanup_project

    def test_get_backup_not_found(self):
        """Get nonexistent backup returns None."""
        result = backups.get_backup("bkp-nonexistent")
        assert result is None

    def test_list_backups_empty(self, cleanup_project):
        """List backups returns empty for new project."""
        result, total = backups.list_backups(project_id=cleanup_project)
        assert result == []
        assert total == 0

    def test_list_backups_with_data(self, cleanup_project):
        """List backups returns created records."""
        backups.create_backup_record(cleanup_project, note="First")
        backups.create_backup_record(cleanup_project, note="Second")

        result, total = backups.list_backups(project_id=cleanup_project)
        assert len(result) == 2
        assert total == 2

    def test_list_backups_filter_by_status(self, cleanup_project):
        """List backups filters by status."""
        b1 = backups.create_backup_record(cleanup_project)
        backups.create_backup_record(cleanup_project)
        backups.update_backup_status(b1["id"], "completed")

        result, _total = backups.list_backups(project_id=cleanup_project, status="completed")
        assert len(result) == 1
        assert result[0]["id"] == b1["id"]

    def test_update_backup_status(self, cleanup_project):
        """Update backup status changes status and timestamps."""
        backup = backups.create_backup_record(cleanup_project)

        updated = backups.update_backup_status(
            backup["id"],
            status="running",
        )
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
        assert completed["status"] == "completed"
        assert completed["completed_at"] is not None
        assert completed["size_bytes"] == 1024000
        assert completed["location"] == "/backups/test"

    def test_update_backup_status_failed(self, cleanup_project):
        """Update backup to failed status includes error message."""
        backup = backups.create_backup_record(cleanup_project)

        failed = backups.update_backup_status(
            backup["id"],
            status="failed",
            error_message="Disk full",
        )
        assert failed["status"] == "failed"
        assert failed["error_message"] == "Disk full"

    def test_delete_backup_record(self, cleanup_project):
        """Delete backup removes record."""
        backup = backups.create_backup_record(cleanup_project)
        assert backups.get_backup(backup["id"]) is not None

        deleted = backups.delete_backup_record(backup["id"])
        assert deleted is True
        assert backups.get_backup(backup["id"]) is None

    def test_delete_backup_not_found(self):
        """Delete nonexistent backup returns False."""
        result = backups.delete_backup_record("bkp-nonexistent")
        assert result is False


class TestScheduleCRUD:
    """Tests for schedule CRUD operations."""

    def test_get_schedule_not_found(self, cleanup_project):
        """Get schedule returns None when not set."""
        result = backups.get_schedule(cleanup_project)
        assert result is None

    def test_upsert_schedule_create(self, cleanup_project):
        """Upsert creates new schedule."""
        schedule = backups.upsert_schedule(
            project_id=cleanup_project,
            enabled=True,
            frequency="daily",
            retention_count=7,
        )

        assert schedule["project_id"] == cleanup_project
        assert schedule["enabled"] is True
        assert schedule["frequency"] == "daily"
        assert schedule["retention_count"] == 7

    def test_upsert_schedule_update(self, cleanup_project):
        """Upsert updates existing schedule."""
        backups.upsert_schedule(cleanup_project, True, "daily", 5)

        updated = backups.upsert_schedule(
            project_id=cleanup_project,
            enabled=False,
            frequency="weekly",
            retention_count=10,
        )

        assert updated["enabled"] is False
        assert updated["frequency"] == "weekly"
        assert updated["retention_count"] == 10

    def test_update_schedule_last_run(self, cleanup_project):
        """Update schedule last run updates timestamps."""
        from datetime import datetime, timedelta

        backups.upsert_schedule(cleanup_project, True, "daily")
        next_run = datetime.now(UTC) + timedelta(days=1)

        result = backups.update_schedule_last_run(cleanup_project, next_run)
        assert result is True

        schedule = backups.get_schedule(cleanup_project)
        assert schedule["last_run_at"] is not None
        assert schedule["next_run_at"] is not None

    def test_list_due_schedules(self, conn, cleanup_project):
        """List due schedules returns schedules ready to run."""
        backups.upsert_schedule(cleanup_project, True, "daily")

        with conn.cursor() as cur:
            cur.execute(
                "UPDATE backup_schedules SET next_run_at = NOW() - INTERVAL '1 hour' WHERE project_id = %s",
                (cleanup_project,),
            )
            conn.commit()

        due = backups.list_due_schedules()
        project_ids = [s["project_id"] for s in due]
        assert cleanup_project in project_ids


class TestStorageSummary:
    """Tests for storage summary functions."""

    def test_get_storage_summary_empty(self, cleanup_project):
        """Storage summary returns zeros for empty project."""
        summary = backups.get_storage_summary(cleanup_project)
        assert summary["total_count"] == 0
        assert summary["total_bytes"] == 0

    def test_get_storage_summary_with_data(self, cleanup_project):
        """Storage summary returns correct counts and sizes."""
        b1 = backups.create_backup_record(cleanup_project)
        b2 = backups.create_backup_record(cleanup_project)

        backups.update_backup_status(b1["id"], "completed", size_bytes=1000)
        backups.update_backup_status(b2["id"], "completed", size_bytes=2000)

        summary = backups.get_storage_summary(cleanup_project)
        assert summary["total_count"] == 2
        assert summary["total_bytes"] == 3000
        assert summary["by_status"]["completed"] == 2

    def test_get_latest_backup(self, cleanup_project):
        """Get latest backup returns most recent completed."""
        b1 = backups.create_backup_record(cleanup_project, note="First")
        b2 = backups.create_backup_record(cleanup_project, note="Second")

        backups.update_backup_status(b1["id"], "completed")
        backups.update_backup_status(b2["id"], "completed")

        latest = backups.get_latest_backup(cleanup_project)
        assert latest is not None
        assert latest["note"] == "Second"

    def test_get_latest_backup_no_completed(self, cleanup_project):
        """Get latest backup returns None when no completed backups."""
        backups.create_backup_record(cleanup_project)

        latest = backups.get_latest_backup(cleanup_project)
        assert latest is None
