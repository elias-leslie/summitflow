"""CLI contracts for configuring and retrying offsite backup sync."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

runner = CliRunner()


def test_storage_probe_failure_returns_nonzero(monkeypatch) -> None:
    from cli.commands import backup_storage
    from cli.main import app

    monkeypatch.setattr(backup_storage, "_api_post", lambda _path: {
        "success": False, "message": "Backup recovery key is not verified",
    })
    result = runner.invoke(app, ["backup", "storage", "test", "local-1"])
    assert result.exit_code == 1
    assert "Backup recovery key is not verified" in result.output


def test_storage_update_merges_offsite_settings_into_existing_backend(monkeypatch) -> None:
    from cli.commands import backup_storage
    from cli.main import app

    captured: dict[str, object] = {}
    monkeypatch.setattr(
        backup_storage,
        "_api_get",
        lambda _path: {
            "id": "local-1",
            "config": {"root_path": "/backup", "path": "project-backups"},
        },
    )

    def put(path, data):
        captured.update({"path": path, "data": data})
        return {"id": "local-1", "config": data["config"]}

    monkeypatch.setattr(backup_storage, "_api_put", put)

    result = runner.invoke(
        app,
        [
            "backup",
            "storage",
            "update",
            "local-1",
            "--offsite-gio-uri",
            "google-drive://account/my-drive-id",
        ],
    )

    assert result.exit_code == 0
    assert captured["path"] == "backup-storage/local-1"
    assert captured["data"] == {
        "config": {
            "root_path": "/backup",
            "path": "project-backups",
            "offsite_gio_uri": "google-drive://account/my-drive-id",
        }
    }


def test_sync_offsite_reports_queued_workflow(monkeypatch) -> None:
    from cli.commands import backup
    from cli.main import app

    class SourceAPI:
        def sync_backup_offsite(self, source_id, backup_id):
            assert source_id == "summitflow"
            assert backup_id == "backup-1"
            return {"task_id": "workflow-1", "status": "queued"}

    monkeypatch.setattr(backup, "_get_source_api", lambda: SourceAPI())

    result = runner.invoke(
        app,
        ["backup", "sync-offsite", "backup-1", "--source", "summitflow"],
    )

    assert result.exit_code == 0
    assert "OFFSITE_SYNC backup-1|source:summitflow|status:queued|task:workflow-1" in result.output


def test_native_rclone_settings_keep_local_storage_and_use_private_ref(monkeypatch) -> None:
    from cli.commands import backup_storage
    from cli.main import app

    captured = {}
    monkeypatch.setattr(backup_storage, "_api_get", lambda _: {"config": {"root_path": "/backup", "path": "project-backups"}})
    def update(path, data):
        captured.update(data["config"])
        return {"id": "local-1"}
    monkeypatch.setattr(backup_storage, "_api_put", update)
    result = runner.invoke(app, ["backup", "storage", "update", "local-1", "--offsite-transport", "rclone", "--offsite-rclone-remote", "drive:bounded", "--offsite-rclone-config", "/private/keys/rclone.conf"])
    assert result.exit_code == 0, result.output
    assert captured == {"root_path": "/backup", "path": "project-backups", "offsite_transport": "rclone", "offsite_rclone_remote": "drive:bounded", "offsite_rclone_config": "/private/keys/rclone.conf"}
    assert "offsite:configured" in result.output


@pytest.mark.parametrize("enabled", [True, False])
def test_native_permanent_expiry_cli_preserves_backend_and_sends_explicit_bool(monkeypatch, enabled):
    from cli.commands import backup_storage
    from cli.main import app

    captured = {}
    original = {"root_path": "/backup", "offsite_transport": "rclone", "offsite_rclone_remote": "drive:bounded"}
    monkeypatch.setattr(backup_storage, "_api_get", lambda _: {"config": original})
    def update(path, data):
        captured.update(data["config"])
        return {"id": "local-1"}
    monkeypatch.setattr(backup_storage, "_api_put", update)
    flag = "--offsite-permanent-expiry" if enabled else "--offsite-trash-expiry"
    result = runner.invoke(app, ["backup", "storage", "update", "local-1", flag, "--offsite-rclone-root-id", "approved-root"])
    assert result.exit_code == 0, result.output
    assert captured == {**original, "offsite_rclone_permanent_expiry": enabled, "offsite_rclone_root_id": "approved-root"}
