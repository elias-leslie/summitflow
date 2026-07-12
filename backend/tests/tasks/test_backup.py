"""Tests for backup tasks."""

from __future__ import annotations

import json
from collections.abc import Generator
from pathlib import Path
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
from app.tasks.backup_drain import drain_pending_backups
from app.tasks.backup_native import SmbUploadResult, drain_pending_archives, run_project_backup
from app.tasks.backup_restore import restore_backup


@pytest.fixture
def conn() -> Generator[Any]:
    """Database connection fixture."""
    with get_connection() as connection:
        yield connection


@pytest.fixture
def cleanup_project(conn: Any) -> Generator[str]:
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
        # Create a backup source so that backups can reference it via source_id FK
        cur.execute(
            """
            INSERT INTO backup_sources (id, name, path, source_type, project_id)
            VALUES (%s, %s, %s, 'project', %s)
            ON CONFLICT (id) DO NOTHING
            """,
            (project_id, "Test Backup Task Project", "/tmp/test-project", project_id),
        )
        conn.commit()

    yield project_id

    with conn.cursor() as cur:
        cur.execute("DELETE FROM backups WHERE project_id = %s", (project_id,))
        cur.execute("DELETE FROM backup_sources WHERE id = %s", (project_id,))
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
        """Parse historical backup output."""
        output = """
        Archive: summitflow-20260314-102435.tar.gz
        Size: 123M
        DB Size: 45M
        Location: //10.0.0.1/share/backup.tar.gz
        Pending: /tmp/backup-pending/summitflow-20260314-102435.tar.gz
        """
        result = _parse_backup_output(output)

        assert result["archive_name"] == "summitflow-20260314-102435.tar.gz"
        assert result["total_bytes"] == (123 * 1024 * 1024)
        assert result["db_bytes"] == (45 * 1024 * 1024)
        assert result["location"] == "//10.0.0.1/share/backup.tar.gz"
        assert result["pending_path"] == (
            "/tmp/backup-pending/summitflow-20260314-102435.tar.gz"
        )

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
        assert "not found" in str(result["error"])

    def test_create_backup_creates_record(self, cleanup_project: str) -> None:
        """Create backup creates a backup record."""
        # Mock native engine to avoid creating an actual archive
        with patch("app.tasks.backup_executor.run_project_backup") as mock_run:
            mock_run.return_value = {
                "total_bytes": 100 * 1024 * 1024,
                "db_bytes": 50 * 1024 * 1024,
                "location": "/backup/test.tar.gz",
                "archive_name": "test.tar.gz",
                "verification": {"verified": True},
            }

            result = create_backup(
                project_id=cleanup_project,
                note="Test backup",
            )

        assert result["status"] == "completed"
        assert "backup_id" in result

        # Verify record was created
        backup = backup_store.get_backup(str(result["backup_id"]))
        assert backup is not None
        assert backup["project_id"] == cleanup_project
        assert backup["status"] == "completed"

    def test_create_backup_quarantines_unverified_archive(
        self, cleanup_project: str
    ) -> None:
        """A produced archive is not success until its integrity gate passes."""
        with patch("app.tasks.backup_executor.run_project_backup") as mock_run:
            mock_run.return_value = {
                "total_bytes": 1024,
                "location": "/backup/unverified.tar.gz",
                "archive_name": "unverified.tar.gz",
                "verification": {
                    "verified": False,
                    "errors": ["Critical: database.sql.gz missing"],
                },
            }

            result = create_backup(project_id=cleanup_project)

        assert result["status"] == "failed"
        assert "database.sql.gz missing" in str(result["error"])
        backup = backup_store.get_backup(str(result["backup_id"]))
        assert backup is not None
        assert backup["status"] == "failed"

    def test_create_backup_handles_failure(self, cleanup_project: str) -> None:
        """Create backup handles script failure."""
        with patch("app.tasks.backup_executor.run_project_backup") as mock_run:
            mock_run.side_effect = RuntimeError("Disk full")

            result = create_backup(project_id=cleanup_project)

        assert result["status"] == "failed"
        assert "Disk full" in str(result["error"])

        # Verify record was marked failed
        backup = backup_store.get_backup(str(result["backup_id"]))
        assert backup is not None
        assert backup["status"] == "failed"

    def test_create_backup_handles_pending_upload(self, cleanup_project: str) -> None:
        """Create backup handles SMB unavailable case."""
        with patch("app.tasks.backup_executor.run_project_backup") as mock_run:
            mock_run.return_value = {
                "archive_name": "test-backup.tar.gz",
                "total_bytes": 100 * 1024 * 1024,
                "db_bytes": 50 * 1024 * 1024,
                "pending_path": "/tmp/test-backup.tar.gz",
                "verification": {
                    "verified": True,
                    "verified_at": "2026-03-14T10:00:00Z",
                    "errors": [],
                    "tree": {},
                    "total_files": 1,
                    "checksum": "sha256:test",
                    "has_db": True,
                },
            }

            result = create_backup(project_id=cleanup_project)

        assert result["status"] == "completed_pending_upload"
        assert result["location"] == "/tmp/test-backup.tar.gz"

        backup = backup_store.get_backup(str(result["backup_id"]))
        assert backup is not None
        assert backup["location"] == "/tmp/test-backup.tar.gz"
        assert backup["status"] == "completed_pending_upload"
        assert backup["name"] == "test-backup.tar.gz"

    def test_create_backup_local_only_records_local_archive_location(self, cleanup_project: str) -> None:
        """Local-only backup mode records the local archive path and skips pending-upload state."""
        with patch("app.tasks.backup_executor.run_project_backup") as mock_run:
            mock_run.return_value = {
                "archive_name": "test-backup.tar.gz",
                "total_bytes": 100 * 1024 * 1024,
                "db_bytes": 50 * 1024 * 1024,
                "location": "/tmp/test-project/backups/test-backup.tar.gz",
                "verification": {
                    "verified": True,
                    "verified_at": "2026-03-14T10:00:00Z",
                    "errors": [],
                    "tree": {},
                    "total_files": 1,
                    "checksum": "sha256:test",
                    "has_db": True,
                },
            }

            result = create_backup(project_id=cleanup_project, local_only=True)

        assert result["status"] == "completed"
        backup = backup_store.get_backup(str(result["backup_id"]))
        assert backup is not None
        assert backup["status"] == "completed"
        assert backup["location"] == "/tmp/test-project/backups/test-backup.tar.gz"
        assert backup["name"] == "test-backup.tar.gz"
        assert backup["db_size_bytes"] == 50 * 1024 * 1024

        assert mock_run.call_args.kwargs["local_only"] is True


class TestNativeLocalStorage:
    """Tests for native local filesystem storage backends."""

    def test_run_project_backup_writes_to_local_storage_backend(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        storage_root = tmp_path / "Backups"

        def fake_create_project_archive(
            _project_path: Path,
            _project_name: str,
            staging: Path,
            _env: dict[str, str],
        ) -> dict[str, object]:
            archive_path = staging / "project-20260505-180000.tar.gz"
            archive_path.write_bytes(b"archive")
            return {
                "archive_name": archive_path.name,
                "archive_path": archive_path,
                "total_bytes": archive_path.stat().st_size,
                "db_bytes": 0,
                "files_bytes": archive_path.stat().st_size,
                "verification": {"verified": True},
            }

        with patch(
            "app.tasks.backup_native._create_project_archive",
            side_effect=fake_create_project_archive,
        ):
            result = run_project_backup(
                project_dir=str(project_dir),
                source_id="source-1",
                env={
                    "STORAGE_BACKEND_TYPE": "local",
                    "LOCAL_BACKUP_ROOT": str(storage_root),
                    "LOCAL_BACKUP_PATH": "project-backups",
                },
            )

        destination = (
            storage_root
            / "project-backups"
            / "source-1"
            / "project-20260505-180000.tar.gz"
        )
        assert destination.read_bytes() == b"archive"
        assert result["location"] == str(destination)


class TestPendingBackupDrain:
    """Tests for pending SMB upload drain behavior."""

    def test_drain_pending_archives_uploads_files_and_records_locations(
        self,
        tmp_path: Path,
    ) -> None:
        pending_dir = tmp_path / ".local" / "share" / "backup-pending"
        pending_dir.mkdir(parents=True)
        archive = pending_dir / "summitflow-20260426-204113.tar.gz"
        archive.write_bytes(b"backup")
        archive.with_suffix(archive.suffix + ".meta").write_text(
            """
            {
              "archive": "summitflow-20260426-204113.tar.gz",
              "project": "summitflow",
              "smb_host": "backup.example.invalid",
              "smb_path": "project-backups",
              "smb_share": "backups"
            }
            """
        )

        def fake_upload(path: Path, archive_name: str, storage: Any) -> SmbUploadResult:
            assert path == archive
            assert archive_name == archive.name
            assert storage.remote_path == "project-backups/summitflow"
            return SmbUploadResult(
                ok=True,
                archive_name=archive_name,
                remote_path=storage.remote_path,
                location=f"{storage.location_prefix}/{archive_name}",
            )

        with (
            patch("app.tasks.backup_native.Path.home", return_value=tmp_path),
            patch("app.tasks.backup_native._smb_upload", side_effect=fake_upload),
        ):
            result = drain_pending_archives()

        assert result["status"] == "success"
        assert result["uploaded"] == 1
        assert result["uploaded_archives"] == {
            archive.name: "//backup.example.invalid/backups/project-backups/summitflow/"
            "summitflow-20260426-204113.tar.gz"
        }
        assert not archive.exists()
        assert not archive.with_suffix(archive.suffix + ".meta").exists()

    def test_drain_pending_archives_preserves_failure_detail(self, tmp_path: Path) -> None:
        pending_dir = tmp_path / ".local" / "share" / "backup-pending"
        pending_dir.mkdir(parents=True)
        archive = pending_dir / "summitflow-20260426-204113.tar.gz"
        archive.write_bytes(b"backup")
        meta_path = archive.with_suffix(archive.suffix + ".meta")
        meta_path.write_text(
            """
            {
              "archive": "summitflow-20260426-204113.tar.gz",
              "project": "summitflow",
              "retry_count": 2,
              "smb_host": "backup.example.invalid",
              "smb_path": "project-backups",
              "smb_share": "backups"
            }
            """
        )

        failed = SmbUploadResult(
            ok=False,
            archive_name=archive.name,
            remote_path="project-backups/summitflow",
            location="//backup.example.invalid/backups/project-backups/summitflow/"
            "summitflow-20260426-204113.tar.gz",
            returncode=1,
            error="upload failed rc=1: NT_STATUS_ACCESS_DENIED",
        )
        with (
            patch("app.tasks.backup_native.Path.home", return_value=tmp_path),
            patch("app.tasks.backup_native._smb_upload", return_value=failed),
        ):
            result = drain_pending_archives()

        assert result["status"] == "partial"
        assert result["failed"] == 1
        assert result["remaining"] == 1
        assert result["failures"][0]["error"] == "upload failed rc=1: NT_STATUS_ACCESS_DENIED"
        meta = json.loads(meta_path.read_text())
        assert meta["retry_count"] == 3
        assert meta["last_error"] == "upload failed rc=1: NT_STATUS_ACCESS_DENIED"
        assert meta["smb_path"] == "project-backups/summitflow"

    def test_drain_pending_backups_reports_file_pending_without_db_rows(self) -> None:
        with (
            patch("app.tasks.backup_drain.backup_store.get_pending_upload_backups", return_value=[]),
            patch(
                "app.tasks.backup_drain.drain_pending_archives",
                return_value={
                    "status": "dry_run",
                    "pending_before": 2,
                    "backups": [{"name": "a.tar.gz"}, {"name": "b.tar.gz"}],
                },
            ),
        ):
            result = drain_pending_backups(dry_run=True)

        assert result["status"] == "dry_run"
        assert result["pending_before"] == 0
        assert result["file_pending"] == 2
        assert result["archives"] == [{"name": "a.tar.gz"}, {"name": "b.tar.gz"}]

    @patch("app.tasks.backup_executor.create_notification")
    def test_create_backup_failure_notification_uses_backup_project(
        self,
        mock_create_notification: MagicMock,
        cleanup_project: str,
    ) -> None:
        """Backup failure notification stays scoped to the failed backup's project."""
        with patch("app.tasks.backup_executor.run_project_backup") as mock_run:
            mock_run.side_effect = RuntimeError("Disk full")

            result = create_backup(project_id=cleanup_project)

        assert result["status"] == "failed"
        mock_create_notification.assert_called_once()
        assert mock_create_notification.call_args.kwargs["project_id"] == cleanup_project


class TestScheduledBackups:
    """Tests for scheduled backup functionality."""

    def test_run_scheduled_backups_no_due_still_runs_expired_cleanup(self) -> None:
        """Expired-record cleanup still runs even when nothing is due."""
        from app.tasks.backup import run_scheduled_backups

        with (
            patch("app.tasks.backup_scheduler.backup_store.fail_stale_running_backups") as mock_stale_fail,
            patch("app.tasks.backup_scheduler.backup_store.cleanup_expired_backup_records") as mock_cleanup,
            patch("app.tasks.backup_scheduler.backup_store.cleanup_stale_backup_records") as mock_stale_cleanup,
            patch("app.tasks.backup_scheduler.cleanup_local_backup_archives") as mock_local_cleanup,
            patch("app.tasks.backup_scheduler.maintenance_store.record_maintenance_run") as mock_record,
        ):
            mock_stale_fail.return_value = 3
            mock_cleanup.return_value = 4
            mock_stale_cleanup.return_value = 2
            mock_local_cleanup.return_value = {"deleted": 5, "bytes_deleted": 123}

            result = run_scheduled_backups()

        assert result["status"] == "success"
        assert result["count"] == 0
        assert result["stale_failed"] == 3
        assert result["stale_cleaned"] == 2
        assert result["expired_cleaned"] == 4
        assert result["local_archives_deleted"] == 5
        assert result["local_bytes_deleted"] == 123
        assert result["rows_cleaned"] == 9
        mock_stale_fail.assert_called_once()
        mock_cleanup.assert_called_once()
        mock_stale_cleanup.assert_called_once()
        mock_local_cleanup.assert_called_once_with(dry_run=False)
        mock_record.assert_called_once()

    def test_run_scheduled_backups_with_due(self, cleanup_project: str, conn: Any) -> None:
        """Run scheduled backups triggers backup for due projects."""
        from app.tasks.backup import run_scheduled_backups

        # Enable the source and make it due for a backup
        backup_store.update_source(cleanup_project, enabled=True)

        with conn.cursor() as cur:
            cur.execute(
                "UPDATE backup_sources SET next_run_at = NOW() - INTERVAL '1 hour' WHERE id = %s",
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

        # Verify source was updated
        source = backup_store.get_source(cleanup_project)
        assert source is not None
        assert source["last_run_at"] is not None
        assert source["next_run_at"] is not None

    def test_run_scheduled_backups_failed_source_does_not_advance_schedule(
        self, cleanup_project: str, conn: Any
    ) -> None:
        """Failed scheduled backups leave the source due so the next run can retry."""
        from app.tasks.backup import run_scheduled_backups

        backup_store.update_source(cleanup_project, enabled=True)

        with conn.cursor() as cur:
            cur.execute(
                "UPDATE backup_sources SET last_run_at = NULL, next_run_at = NOW() - INTERVAL '1 hour' WHERE id = %s",
                (cleanup_project,),
            )
            conn.commit()

        with patch("app.tasks.backup_scheduler.create_backup") as mock_create:
            mock_create.return_value = {"status": "failed", "error": "Disk full"}

            result = run_scheduled_backups()

        assert result["status"] == "partial"
        assert result["failed"] >= 1
        source = backup_store.get_source(cleanup_project)
        assert source is not None
        assert source["last_run_at"] is None
        assert source["next_run_at"] is not None

    def test_run_scheduled_backups_treats_pending_upload_as_success(
        self, cleanup_project: str, conn: Any
    ) -> None:
        """Pending-upload results should still advance the source schedule."""
        from app.tasks.backup import run_scheduled_backups

        backup_store.update_source(cleanup_project, enabled=True)

        with conn.cursor() as cur:
            cur.execute(
                "UPDATE backup_sources SET last_run_at = NULL, next_run_at = NOW() - INTERVAL '1 hour' WHERE id = %s",
                (cleanup_project,),
            )
            conn.commit()

        with patch("app.tasks.backup_scheduler.create_backup") as mock_create:
            mock_create.return_value = {
                "status": "completed_pending_upload",
                "backup_id": "mock-pending-upload-backup",
            }

            result = run_scheduled_backups()

        assert result["status"] == "success"
        assert result["succeeded"] >= 1
        assert result["failed"] == 0
        source = backup_store.get_source(cleanup_project)
        assert source is not None
        assert source["last_run_at"] is not None
        assert source["next_run_at"] is not None

    @pytest.fixture()
    def secondary_source(self, cleanup_project: str, conn: Any):
        """Insert a secondary backup source and guarantee its removal after the test."""
        source_id = f"{cleanup_project}-secondary"
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO backup_sources (
                    id, name, path, source_type, project_id, enabled, frequency, next_run_at
                )
                VALUES (%s, %s, %s, 'project', %s, TRUE, 'daily', NOW() - INTERVAL '1 hour')
                ON CONFLICT (id) DO NOTHING
                """,
                (source_id, "Secondary Source", "/tmp/test-project-2", cleanup_project),
            )
            conn.commit()
        yield source_id
        with conn.cursor() as cur:
            cur.execute("DELETE FROM backup_sources WHERE id = %s", (source_id,))
            conn.commit()

    def test_run_scheduled_backups_continues_after_one_source_fails(
        self, cleanup_project: str, conn: Any, secondary_source: str
    ) -> None:
        """One failing source should not block later due sources in the same sweep."""
        from app.tasks.backup import run_scheduled_backups

        second_source_id = secondary_source
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE backup_sources SET enabled = TRUE, last_run_at = NULL, next_run_at = NOW() - INTERVAL '1 hour' WHERE id = %s",
                (cleanup_project,),
            )
            conn.commit()

        def _create_backup(**kwargs: Any) -> dict[str, str]:
            if kwargs["source_id"] == cleanup_project:
                return {"status": "failed", "error": "Disk full"}
            return {"status": "completed", "backup_id": "backup-ok"}

        with patch("app.tasks.backup_scheduler.create_backup", side_effect=_create_backup):
            result = run_scheduled_backups()

        assert result["count"] >= 2
        assert result["failed"] >= 1
        assert result["succeeded"] >= 1

        first_source = backup_store.get_source(cleanup_project)
        second_source = backup_store.get_source(second_source_id)
        assert first_source is not None
        assert second_source is not None
        assert first_source["last_run_at"] is None
        assert second_source["last_run_at"] is not None


class TestRestoreBackup:
    """Tests for native backup restore selection."""

    def test_restore_backup_fails_when_archive_is_not_local_or_pending(self) -> None:
        """Remote-only backups fail explicitly instead of falling back to latest."""
        backup_record = {
            "id": "bkp-1",
            "project_id": "summitflow",
            "source_id": "summitflow",
            "location": "//10.0.0.1/nas-share/project-backups/summitflow/summitflow-20260314-102435.tar.gz",
            "name": "stale-name",
        }

        with (
            patch("app.tasks.backup_restore.get_project_root", return_value="/tmp/test-project"),
            patch("app.tasks.backup_restore.backup_store.get_backup", return_value=backup_record),
        ):
            result = restore_backup(project_id="summitflow", backup_id="bkp-1", dry_run=True)

        assert result["status"] == "failed"
        assert "summitflow-20260314-102435.tar.gz" in result["error"]

    def test_restore_backup_uses_exact_local_file_path(self, tmp_path: Path) -> None:
        """If the backup record already has a local path, restore uses that path."""
        archive_path = tmp_path / "exact-backup.tar.gz"
        backup_record = {
            "id": "bkp-2",
            "project_id": "summitflow",
            "source_id": "summitflow",
            "location": str(archive_path),
            "name": "exact-backup.tar.gz",
        }

        with (
            patch("app.tasks.backup_restore.get_project_root", return_value=str(tmp_path)),
            patch("app.tasks.backup_restore.backup_store.get_backup", return_value=backup_record),
            patch("app.tasks.backup_restore.restore_archive") as mock_restore,
        ):
            archive_path.write_bytes(b"archive")
            mock_restore.return_value = {"status": "completed", "dry_run": True, "archive": str(archive_path)}
            result = restore_backup(project_id="summitflow", backup_id="bkp-2", dry_run=True)

        assert result["status"] == "completed"
        assert mock_restore.call_args.args[0] == archive_path

    def test_restore_backup_rejects_checksum_mismatch(self, tmp_path: Path) -> None:
        """A modified archive must never reach extraction or database restore."""
        archive_path = tmp_path / "modified-backup.tar.gz"
        archive_path.write_bytes(b"modified archive")
        backup_record = {
            "id": "bkp-3",
            "project_id": "summitflow",
            "source_id": "summitflow",
            "location": str(archive_path),
            "name": archive_path.name,
            "checksum": "sha256:" + "0" * 64,
        }

        with (
            patch("app.tasks.backup_restore.get_project_root", return_value=str(tmp_path)),
            patch(
                "app.tasks.backup_restore.backup_store.get_backup",
                return_value=backup_record,
            ),
            patch("app.tasks.backup_restore.restore_archive") as mock_restore,
        ):
            result = restore_backup(
                project_id="summitflow",
                backup_id="bkp-3",
                dry_run=True,
            )

        assert result["status"] == "failed"
        assert "checksum mismatch" in result["error"].lower()
        mock_restore.assert_not_called()

    def test_restore_backup_refuses_explicitly_unverified_record(
        self, tmp_path: Path
    ) -> None:
        archive_path = tmp_path / "unverified-backup.tar.gz"
        archive_path.write_bytes(b"archive")
        backup_record = {
            "id": "bkp-4",
            "project_id": "summitflow",
            "source_id": "summitflow",
            "location": str(archive_path),
            "name": archive_path.name,
            "verified": False,
        }

        with (
            patch("app.tasks.backup_restore.get_project_root", return_value=str(tmp_path)),
            patch(
                "app.tasks.backup_restore.backup_store.get_backup",
                return_value=backup_record,
            ),
            patch("app.tasks.backup_restore.restore_archive") as mock_restore,
        ):
            result = restore_backup(
                project_id="summitflow",
                backup_id="bkp-4",
                dry_run=False,
            )

        assert result["status"] == "failed"
        assert "failed archive verification" in result["error"].lower()
        mock_restore.assert_not_called()
