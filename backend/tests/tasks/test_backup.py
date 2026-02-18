"""Tests for backup tasks."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.storage import backups as backup_store
from app.storage.connection import get_connection
from app.tasks.backup import (
    _calculate_next_run,
    _parse_backup_output,
    _parse_size,
    create_backup,
)


@pytest.fixture
def conn() -> Generator[Any, None, None]:
    """Database connection fixture."""
    with get_connection() as connection:
        yield connection


@pytest.fixture
def cleanup_project(conn: Any) -> Generator[str, None, None]:
    """Fixture to clean up test project data after tests."""
    project_id = "test-backup-task-project"

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO projects (id, name, base_url, root_path)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (id) DO NOTHING
            """,
            (project_id, "Test Backup Task Project", "http://localhost", "/tmp/test-project"),
        )
        conn.commit()

    yield project_id

    with conn.cursor() as cur:
        cur.execute("DELETE FROM backups WHERE project_id = %s", (project_id,))
        cur.execute("DELETE FROM backup_schedules WHERE project_id = %s", (project_id,))
        cur.execute("DELETE FROM projects WHERE id = %s", (project_id,))
        conn.commit()


class TestParseFunctions:
    """Tests for parsing helper functions."""

    def test_parse_size_bytes(self) -> None:
        """Parse size in bytes."""
        assert _parse_size("12345 bytes") == 12345
        assert _parse_size("0 bytes") == 0

    def test_parse_size_units(self) -> None:
        """Parse size with K/M/G units."""
        assert _parse_size("1K") == 1024
        assert _parse_size("1M") == 1024 * 1024
        assert _parse_size("1G") == 1024 * 1024 * 1024
        assert _parse_size("1.5M") == int(1.5 * 1024 * 1024)

    def test_parse_size_plain_number(self) -> None:
        """Parse plain number."""
        assert _parse_size("12345") == 12345

    def test_parse_size_invalid(self) -> None:
        """Parse invalid size returns None."""
        assert _parse_size("invalid") is None
        assert _parse_size("") is None

    def test_parse_backup_output(self) -> None:
        """Parse backup.sh output."""
        output = """
        Size: 123M
        DB Size: 45M
        Location: //192.168.8.128/share/backup.tar.gz
        """
        result = _parse_backup_output(output)

        assert result["total_bytes"] == (123 * 1024 * 1024)
        assert result["db_bytes"] == (45 * 1024 * 1024)
        assert result["location"] == "//192.168.8.128/share/backup.tar.gz"

    def test_calculate_next_run_daily(self) -> None:
        """Calculate daily next run."""
        from datetime import UTC, datetime, timedelta

        next_run = _calculate_next_run("daily")
        expected = datetime.now(UTC) + timedelta(days=1)
        assert abs((next_run - expected).total_seconds()) < 5

    def test_calculate_next_run_weekly(self) -> None:
        """Calculate weekly next run."""
        from datetime import UTC, datetime, timedelta

        next_run = _calculate_next_run("weekly")
        expected = datetime.now(UTC) + timedelta(weeks=1)
        assert abs((next_run - expected).total_seconds()) < 5


class TestCreateBackupTask:
    """Tests for create_backup task."""

    def test_create_backup_project_not_found(self, conn: Any) -> None:
        """Create backup fails for nonexistent project."""
        # Use a project ID that doesn't exist
        result = create_backup(
            project_id="nonexistent-project",
            note="Test",
        )

        assert result["status"] == "failed"
        assert "not found" in result["error"]

    def test_create_backup_creates_record(self, cleanup_project: str) -> None:
        """Create backup creates a backup record."""
        # Mock subprocess to avoid running actual backup
        with patch("app.tasks.backup_executor.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="Size: 100M\nDB Size: 50M\nLocation: /backup/test.tar.gz",
                stderr="",
            )

            result = create_backup(
                project_id=cleanup_project,
                note="Test backup",
            )

        assert result["status"] == "completed"
        assert "backup_id" in result

        # Verify record was created
        backup = backup_store.get_backup(result["backup_id"])
        assert backup is not None
        assert backup["project_id"] == cleanup_project
        assert backup["status"] == "completed"

    def test_create_backup_handles_failure(self, cleanup_project: str) -> None:
        """Create backup handles script failure."""
        with patch("app.tasks.backup_executor.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stdout="",
                stderr="Disk full",
            )

            result = create_backup(project_id=cleanup_project)

        assert result["status"] == "failed"
        assert "Disk full" in result["error"]

        # Verify record was marked failed
        backup = backup_store.get_backup(result["backup_id"])
        assert backup is not None
        assert backup["status"] == "failed"

    def test_create_backup_handles_pending_upload(self, cleanup_project: str) -> None:
        """Create backup handles SMB unavailable case."""
        with patch("app.tasks.backup_executor.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stdout="Backup saved locally (SMB unavailable)",
                stderr="",
            )

            result = create_backup(project_id=cleanup_project)

        assert result["status"] == "completed"
        assert result["location"] == "pending_upload"


class TestScheduledBackups:
    """Tests for scheduled backup functionality."""

    def test_run_scheduled_backups_no_due(self) -> None:
        """Run scheduled backups with no due schedules."""
        from app.tasks.backup import run_scheduled_backups

        result = run_scheduled_backups()

        assert result["status"] == "success"
        assert result["count"] == 0

    def test_run_scheduled_backups_with_due(self, cleanup_project: str, conn: Any) -> None:
        """Run scheduled backups triggers backup for due projects."""
        from app.tasks.backup import run_scheduled_backups

        # Create a schedule that is due
        backup_store.upsert_schedule(cleanup_project, True, "daily")

        with conn.cursor() as cur:
            cur.execute(
                "UPDATE backup_schedules SET next_run_at = NOW() - INTERVAL '1 hour' WHERE project_id = %s",
                (cleanup_project,),
            )
            conn.commit()

        # Mock create_backup to avoid actual execution
        with patch("app.tasks.backup_scheduler.create_backup") as mock_create:
            mock_create.return_value = {"status": "completed", "backup_id": "mock-backup-id"}

            result = run_scheduled_backups()

        assert result["status"] == "success"
        assert result["count"] >= 1

        # Verify create_backup was called
        mock_create.assert_called()

        # Verify schedule was updated
        schedule = backup_store.get_schedule(cleanup_project)
        assert schedule is not None
        assert schedule["last_run_at"] is not None
        assert schedule["next_run_at"] is not None
