"""CLI contracts for configuring and retrying offsite backup sync."""

from __future__ import annotations

from typer.testing import CliRunner

runner = CliRunner()


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
