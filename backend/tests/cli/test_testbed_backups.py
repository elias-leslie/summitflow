"""Tests for testbed backup library helpers."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


def test_reset_testbed_to_baseline_skips_unknown_global_rebuild(monkeypatch, tmp_path: Path) -> None:
    from cli.lib.testbed_backups import reset_testbed_to_baseline

    project_root = tmp_path / "test2"
    project_root.mkdir()

    monkeypatch.setattr(
        "cli.lib.testbed_backups._require_baseline_backup",
        lambda project_id, backup_id=None: {
            "id": "bkp-123",
            "project_id": project_id,
            "name": "test2-baseline.tar.gz",
            "db_size_bytes": 0,
            "verification_json": {
                "has_db": False,
                "testbed_baseline": {"snapshot_id": "snap-123"},
            },
        },
    )
    monkeypatch.setattr("cli.lib.testbed_backups._project_root", lambda project_id: project_root)
    monkeypatch.setattr(
        "cli.lib.testbed_backups.restore_project_snapshot",
        lambda snapshot_id, project_id, cwd=None: type(
            "Snapshot", (), {"id": snapshot_id, "name": "baseline"}
        )(),
    )

    def _fake_run(cmd, cwd=None, capture_output=True, text=True, check=False):
        del cwd, capture_output, text, check
        assert cmd == ["rebuild.sh", "test2"]
        return subprocess.CompletedProcess(cmd, 1, "", "Unknown project: test2")

    monkeypatch.setattr("cli.lib.testbed_backups.subprocess.run", _fake_run)

    result = reset_testbed_to_baseline("test2", rebuild=True)

    assert result["rebuild_ran"] is False
    assert result["rebuild_method"] == "skipped"
    assert "Unknown project 'test2'" in str(result["rebuild_reason"])


def test_preview_testbed_reset_blocks_when_called_inside_target_root(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from cli.lib.testbed_backups import TestbedBackupError, preview_testbed_reset

    project_root = tmp_path / "test2"
    project_root.mkdir()
    monkeypatch.chdir(project_root)
    monkeypatch.setattr(
        "cli.lib.testbed_backups._require_baseline_backup",
        lambda project_id, backup_id=None: {
            "id": "bkp-123",
            "project_id": project_id,
            "name": "test2-baseline.tar.gz",
            "verification_json": {
                "has_db": False,
                "testbed_baseline": {
                    "project_root": str(project_root),
                    "snapshot_id": "snap-123",
                },
            },
        },
    )

    with pytest.raises(TestbedBackupError, match="outside the target project root"):
        preview_testbed_reset("test2")


def test_capture_testbed_baseline_uses_local_backup_by_default(monkeypatch, tmp_path: Path) -> None:
    from cli.lib.testbed_backups import capture_testbed_baseline

    project_root = tmp_path / "test2"
    project_root.mkdir()
    captured: dict[str, object] = {}

    monkeypatch.setattr("cli.lib.testbed_backups._project_root", lambda project_id: project_root)
    monkeypatch.setattr("cli.lib.testbed_backups._git_status_lines", lambda repo_root: [])
    monkeypatch.setattr("cli.lib.testbed_backups._git_branch", lambda repo_root: "main")
    monkeypatch.setattr("cli.lib.testbed_backups._git_head", lambda repo_root: "abc123")
    monkeypatch.setattr(
        "cli.lib.testbed_backups.capture_snapshot",
        lambda snapshot_name, project_id, cwd=None, source="manual": type(
            "Snapshot",
            (),
            {
                "id": "snap-123",
                "name": snapshot_name,
                "snapshot_path": "/tmp/snap-123",
                "created_at": "2026-03-25T00:00:00+00:00",
                "head_ref": "refs/heads/main",
            },
        )(),
    )

    def _fake_create_backup(
        project_id: str,
        note: str | None = None,
        backup_type: str = "manual",
        keep_local: bool = False,
        retention_days: int | None = None,
        source_id: str | None = None,
        local_only: bool = False,
    ) -> dict[str, object]:
        captured["project_id"] = project_id
        captured["note"] = note
        captured["keep_local"] = keep_local
        captured["local_only"] = local_only
        return {
            "status": "completed",
            "backup_id": "bkp-123",
            "location": str(tmp_path / "external" / "test2-20260325-000000.tar.gz"),
        }

    monkeypatch.setattr("cli.lib.testbed_backups.create_backup", _fake_create_backup)
    monkeypatch.setattr(
        "cli.lib.testbed_backups.backup_store.merge_backup_verification_json",
        lambda backup_id, verification_updates: {
            "id": backup_id,
            "name": "test2-20260325-000000.tar.gz",
            "status": "completed",
            "location": "/tmp/test2/backups/test2-20260325-000000.tar.gz",
        },
    )

    result = capture_testbed_baseline("test2")

    assert captured["project_id"] == "test2"
    assert captured["local_only"] is True
    assert captured["keep_local"] is False
    assert result["backup_id"] == "bkp-123"


def test_capture_testbed_baseline_relocates_repo_local_archive(monkeypatch, tmp_path: Path) -> None:
    from cli.lib.testbed_backups import capture_testbed_baseline

    project_root = tmp_path / "test2"
    project_root.mkdir()
    repo_backup_dir = project_root / "backups"
    repo_backup_dir.mkdir()
    repo_archive = repo_backup_dir / "test2-20260325-000000.tar.gz"
    repo_archive.write_text("archive-bytes")
    relocated: dict[str, object] = {}

    monkeypatch.setenv("ST_TESTBED_BACKUP_ROOT", str(tmp_path / "testbed-store"))
    monkeypatch.setattr("cli.lib.testbed_backups._project_root", lambda project_id: project_root)
    monkeypatch.setattr("cli.lib.testbed_backups._git_status_lines", lambda repo_root: [])
    monkeypatch.setattr("cli.lib.testbed_backups._git_branch", lambda repo_root: "main")
    monkeypatch.setattr("cli.lib.testbed_backups._git_head", lambda repo_root: "abc123")
    monkeypatch.setattr(
        "cli.lib.testbed_backups.capture_snapshot",
        lambda snapshot_name, project_id, cwd=None, source="manual": type(
            "Snapshot",
            (),
            {
                "id": "snap-123",
                "name": snapshot_name,
                "snapshot_path": "/tmp/snap-123",
                "created_at": "2026-03-25T00:00:00+00:00",
                "head_ref": "refs/heads/main",
            },
        )(),
    )
    monkeypatch.setattr(
        "cli.lib.testbed_backups.create_backup",
        lambda **kwargs: {
            "status": "completed",
            "backup_id": "bkp-123",
            "location": str(repo_archive),
        },
    )
    monkeypatch.setattr(
        "cli.lib.testbed_backups.backup_store.update_backup_status",
        lambda backup_id, status, location=None, **kwargs: relocated.update(
            {"backup_id": backup_id, "status": status, "location": location}
        )
        or {"id": backup_id, "status": status, "location": location},
    )
    monkeypatch.setattr(
        "cli.lib.testbed_backups.backup_store.merge_backup_verification_json",
        lambda backup_id, verification_updates: {
            "id": backup_id,
            "name": "test2-20260325-000000.tar.gz",
            "status": "completed",
            "location": relocated["location"],
        },
    )

    result = capture_testbed_baseline("test2")

    archive_location = Path(str(result["archive_location"]))
    assert archive_location.exists()
    assert project_root not in archive_location.parents
    assert not repo_archive.exists()
    assert relocated["location"] == str(archive_location)
