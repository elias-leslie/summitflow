from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from typer.testing import CliRunner

runner = CliRunner()


def test_backup_restore_into_runs_isolated_restore_and_states_db_limit(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from cli.commands import backup_runtime
    from cli.main import app

    destination = tmp_path / "recovered"
    restore = MagicMock(
        return_value={
            "status": "completed",
            "isolated": True,
            "database_copy": str(destination / ".summitflow-recovery" / "database.sql.gz"),
            "evidence": {"ok": True, "git_restored": True},
        }
    )
    monkeypatch.setattr(backup_runtime, "restore_backup_isolated", restore)

    result = runner.invoke(
        app,
        [
            "backup",
            "restore",
            "backup-1",
            "--source",
            "summitflow",
            "--into",
            str(destination),
        ],
    )

    assert result.exit_code == 0, result.output
    restore.assert_called_once_with(
        "backup-1",
        destination,
        expected_source_id="summitflow",
        archive_file=None,
    )
    assert "Database dumps are copied for inspection; no database was restored." in result.output


def test_backup_restore_into_rejects_normal_restore_modes(tmp_path: Path) -> None:
    from cli.main import app

    result = runner.invoke(
        app,
        [
            "backup",
            "restore",
            "backup-1",
            "--into",
            str(tmp_path / "recovered"),
            "--dry-run",
        ],
    )

    assert result.exit_code == 1
    assert "--into cannot be combined" in result.output


def test_backup_restore_into_forwards_checksum_proven_download(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from cli.commands import backup_runtime
    from cli.main import app

    archive = tmp_path / "downloaded.tar.gz.age"
    archive.write_bytes(b"ciphertext")
    destination = tmp_path / "recovered"
    restore = MagicMock(
        return_value={"status": "completed", "isolated": True, "database_copy": None}
    )
    monkeypatch.setattr(backup_runtime, "restore_backup_isolated", restore)

    result = runner.invoke(
        app,
        [
            "backup",
            "restore",
            "backup-1",
            "--file",
            str(archive),
            "--into",
            str(destination),
        ],
    )

    assert result.exit_code == 0, result.output
    restore.assert_called_once_with(
        "backup-1",
        destination,
        expected_source_id=None,
        archive_file=archive,
    )
