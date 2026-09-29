from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

runner = CliRunner()


def test_isolated_restore_forwards_remote_and_canonical_roots(tmp_path: Path, monkeypatch) -> None:
    from cli.commands import backup
    from cli.main import app

    restore = MagicMock()
    monkeypatch.setattr(backup, "restore_backup_isolated_command", restore)
    destination = tmp_path / "recovered"
    codex = tmp_path / "codex"
    skills = tmp_path / "skills"
    result = runner.invoke(app, [
        "backup", "restore", "backup-1", "--into", str(destination), "--remote",
        "--source-root", f"codex-config={codex}", "--source-root", f"agent-skills={skills}",
    ])
    assert result.exit_code == 0, result.output
    assert restore.call_args.kwargs["remote"] is True
    assert restore.call_args.kwargs["destination_roots"] == {"codex-config": codex, "agent-skills": skills}


@pytest.mark.parametrize("args", [
    ["--remote"],
    ["--source-root", "codex-config=/fixture/codex"],
    ["--into", "/fixture/restore", "--source-root", "codex-config=relative"],
    ["--into", "/fixture/restore", "--source-root", "unknown=/fixture/source"],
    ["--into", "/fixture/restore", "--source-root", "codex-config=/fixture/codex", "--source-root", "codex-config=/fixture/other"],
])
def test_isolated_restore_rejects_invalid_repository_or_mapping_options(monkeypatch, args) -> None:
    from cli.commands import backup
    from cli.main import app

    restore = MagicMock()
    monkeypatch.setattr(backup, "restore_backup_isolated_command", restore)
    result = runner.invoke(app, ["backup", "restore", "backup-1", *args])
    assert result.exit_code == 1
    restore.assert_not_called()

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
