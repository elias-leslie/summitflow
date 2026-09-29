"""CLI pilot selection, file-reference configuration and repository actions."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

runner = CliRunner()


@pytest.mark.parametrize("args,source", [
    (["backup", "create"], None),
    (["backup", "create", "--source", "source"], "source"),
    (["backup", "source", "create", "source"], "source"),
])
def test_create_explicit_backend_is_forwarded(monkeypatch, args, source):
    from cli.commands import backup
    from cli.main import app

    create = MagicMock(return_value={"task_id": "fixture-task"})
    api = SimpleNamespace(create_backup=create, create_source_backup=create)
    monkeypatch.setattr(backup, "_get_project_api", lambda: api)
    monkeypatch.setattr(backup, "_get_source_api", lambda: api)

    result = runner.invoke(app, [*args, "--storage-backend", "pilot"])

    assert result.exit_code == 0, result.output
    expected = {"note": None, "keep_local": False, "storage_backend_id": "pilot"}
    if source is None:
        create.assert_called_once_with(**expected)
    else:
        create.assert_called_once_with(source, **expected)


@pytest.mark.parametrize("source", [False, True])
@pytest.mark.parametrize("backend", [None, "pilot"])
def test_api_clients_omit_optional_backend_unless_selected(monkeypatch, source, backend):
    from cli.commands import backup_api

    response = MagicMock(status_code=200)
    response.json.return_value = {"task_id": "fixture-task"}
    post = MagicMock(return_value=response)
    monkeypatch.setattr(backup_api.httpx, "post", post)
    if source:
        backup_api.BackupSourceAPI("https://fixture.invalid/api").create_source_backup("source", storage_backend_id=backend)
    else:
        backup_api.BackupProjectAPI("https://fixture.invalid/api", "project").create_backup(storage_backend_id=backend)

    expected = {"note": None, "keep_local": False}
    if backend is not None:
        expected["storage_backend_id"] = backend
    assert post.call_args.kwargs["json"] == expected


@pytest.mark.parametrize("name,path", [
    ("codex-config", "/fixture/.codex"),
    ("claude-config", "/fixture/.claude"),
    ("agent-skills", "/fixture/.agents/skills"),
    ("claude-json", "/fixture/.claude.json"),
])
def test_register_explicit_config_directory_or_file(monkeypatch, name, path):
    from cli.commands import backup
    from cli.main import app

    register = MagicMock(return_value={"id": name, "path": path})
    monkeypatch.setattr(backup, "_get_source_api", lambda: SimpleNamespace(register_source=register))

    result = runner.invoke(app, ["backup", "source", "register", name, "--path", path])

    assert result.exit_code == 0, result.output
    register.assert_called_once_with(name, name=name, path=path, source_type="config", project_id=None)


def test_register_source_client_uses_existing_post(monkeypatch):
    from cli.commands import backup_api

    response = MagicMock(status_code=201)
    response.json.return_value = {"id": "claude-json"}
    post = MagicMock(return_value=response)
    monkeypatch.setattr(backup_api.httpx, "post", post)
    backup_api.BackupSourceAPI("https://fixture.invalid/api").register_source(
        "claude-json", name="Claude config", path="/fixture/.claude.json",
    )
    post.assert_called_once_with("https://fixture.invalid/api/backup-sources", json={
        "id": "claude-json", "name": "Claude config", "path": "/fixture/.claude.json", "source_type": "config",
    }, timeout=30.0)


def test_restic_storage_add_is_nondefault_and_only_passes_references(monkeypatch):
    from cli.commands import backup_storage
    from cli.main import app

    post = MagicMock(side_effect=[{"id": "pilot", "name": "Pilot"}, {"success": True}])
    monkeypatch.setattr(backup_storage, "_api_post", post)
    result = runner.invoke(app, [
        "backup", "storage", "add", "--type", "local", "--engine", "restic", "--name", "Pilot",
        "--local-repository", "/backup/restic", "--local-password-file", "/private/local-password",
        "--remote-repository", "rclone:drive:SummitFlow/restic", "--remote-password-file", "/private/remote-password",
        "--key-directory", "/private", "--rclone-config", "/private/rclone.conf", "--no-interactive",
    ])

    assert result.exit_code == 0, result.output
    assert post.call_args_list[0].args == ("backup-storage", {
        "name": "Pilot", "backend_type": "local", "is_default": False,
        "config": {"engine": "restic", "restic_local_repository": "/backup/restic",
                   "restic_remote_repository": "rclone:drive:SummitFlow/restic",
                   "restic_local_password_file": "/private/local-password",
                   "restic_remote_password_file": "/private/remote-password",
                   "restic_key_directory": "/private", "restic_rclone_config": "/private/rclone.conf"},
    })
    assert post.call_args_list[1].args == ("backup-storage/pilot/test",)


def test_restic_storage_add_rejects_inline_password_before_post(monkeypatch):
    from cli.commands import backup_storage
    from cli.main import app

    post = MagicMock()
    monkeypatch.setattr(backup_storage, "_api_post", post)
    result = runner.invoke(app, ["backup", "storage", "add", "--type", "local", "--engine", "restic", "--password", "fixture-inline"])
    assert result.exit_code != 0
    post.assert_not_called()


def test_restic_storage_add_defaults_key_directory_to_canonical_root(monkeypatch):
    from app.services import backup_keys
    from cli.commands import backup_storage
    from cli.main import app

    monkeypatch.setattr(backup_keys, "backup_key_directory", lambda: Path("/fixture/canonical-keyroot"))
    post = MagicMock(side_effect=[{"id": "pilot", "name": "Pilot"}, {"success": True}])
    monkeypatch.setattr(backup_storage, "_api_post", post)
    result = runner.invoke(app, [
        "backup", "storage", "add", "--type", "local", "--engine", "restic",
        "--local-repository", "/backup/restic", "--local-password-file", "/fixture/canonical-keyroot/local-password",
    ])
    assert result.exit_code == 0, result.output
    assert post.call_args_list[0].args[1]["config"]["restic_key_directory"] == "/fixture/canonical-keyroot"


def test_legacy_local_storage_add_keeps_default_and_payload(monkeypatch):
    from cli.commands import backup_storage
    from cli.main import app

    post = MagicMock(side_effect=[{"id": "local", "name": "Local"}, {"success": True}])
    monkeypatch.setattr(backup_storage, "_api_post", post)
    result = runner.invoke(app, ["backup", "storage", "add", "--type", "local", "--root-path", "/backup", "--no-interactive"])
    assert result.exit_code == 0, result.output
    assert post.call_args_list[0].args[1] == {
        "name": "Local /backup", "backend_type": "local", "config": {"root_path": "/backup"}, "is_default": True,
    }


def test_storage_update_merges_pilot_settings_without_changing_default(monkeypatch):
    from cli.commands import backup_storage
    from cli.main import app

    monkeypatch.setattr(backup_storage, "_api_get", lambda _: {"config": {"root_path": "/backup", "path": "legacy"}})
    put = MagicMock(return_value={"id": "pilot"})
    monkeypatch.setattr(backup_storage, "_api_put", put)
    result = runner.invoke(app, [
        "backup", "storage", "update", "pilot", "--engine", "restic",
        "--local-repository", "/backup/restic", "--local-password-file", "/private/local-password",
        "--key-directory", "/private",
    ])
    assert result.exit_code == 0, result.output
    assert put.call_args.args[1] == {"config": {
        "root_path": "/backup", "path": "legacy", "engine": "restic",
        "restic_local_repository": "/backup/restic", "restic_local_password_file": "/private/local-password",
        "restic_key_directory": "/private",
    }}


@pytest.mark.parametrize("command,tail,path,method", [
    ("initialize", [], "backup-storage/pilot/initialize?local_only=false", "_api_post"),
    ("initialize", ["--local-only"], "backup-storage/pilot/initialize?local_only=true", "_api_post"),
    ("status", [], "backup-storage/pilot/repository", "_api_get"),
    ("maintenance", [], "backup-storage/pilot/maintenance?dry_run=true", "_api_post"),
    ("maintenance", ["--preview"], "backup-storage/pilot/maintenance?dry_run=true", "_api_post"),
    ("maintenance", ["--apply"], "backup-storage/pilot/maintenance?dry_run=false", "_api_post"),
])
def test_repository_commands_are_explicit_and_maintenance_defaults_to_preview(monkeypatch, command, tail, path, method):
    from cli.commands import backup_storage
    from cli.main import app

    request = MagicMock(return_value={"status": "fixture"})
    monkeypatch.setattr(backup_storage, method, request)
    result = runner.invoke(app, ["backup", "storage", command, "pilot", *tail])
    assert result.exit_code == 0, result.output
    if command in {"initialize", "maintenance"}:
        request.assert_called_once_with(path, timeout=backup_storage.LONG_RUNNING_TIMEOUT)
    else:
        request.assert_called_once_with(path)


def test_long_running_storage_requests_keep_connection_timeout_without_read_deadline(monkeypatch):
    from cli.commands import backup_storage

    response = MagicMock(status_code=200)
    response.json.return_value = {"status": "complete"}
    post = MagicMock(return_value=response)
    monkeypatch.setattr(backup_storage, "_get_base_url", lambda: "https://fixture.invalid/api")
    monkeypatch.setattr(backup_storage.httpx, "post", post)

    assert backup_storage._api_post(
        "backup-storage/pilot/initialize", timeout=backup_storage.LONG_RUNNING_TIMEOUT,
    ) == {"status": "complete"}
    timeout = post.call_args.kwargs["timeout"]
    assert timeout.connect == timeout.write == timeout.pool == 30.0
    assert timeout.read is None
