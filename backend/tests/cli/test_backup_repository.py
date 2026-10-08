"""CLI pilot selection, file-reference configuration and repository actions."""

from __future__ import annotations

import json
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


@pytest.mark.parametrize("flag,key,value", [
    ("--automatic-maintenance", "restic_automatic_maintenance", True),
    ("--no-automatic-maintenance", "restic_automatic_maintenance", False),
    ("--offsite-prune-qualified", "restic_offsite_prune_qualified", True),
    ("--no-offsite-prune-qualified", "restic_offsite_prune_qualified", False),
])
def test_storage_update_merges_explicit_policy_without_changing_repository(monkeypatch, flag, key, value):
    from cli.commands import backup_storage
    from cli.main import app

    config = {
        "engine": "restic", "restic_local_repository": "/backup/restic",
        "restic_remote_repository": "rclone:drive:bounded",
        "restic_local_password_file": "/private/local-password",
        "restic_automatic_maintenance": not value,
        "restic_offsite_prune_qualified": not value,
    }
    monkeypatch.setattr(backup_storage, "_api_get", lambda _: {"config": config})
    put = MagicMock(return_value={"id": "pilot"})
    monkeypatch.setattr(backup_storage, "_api_put", put)

    result = runner.invoke(app, ["backup", "storage", "update", "pilot", flag])

    assert result.exit_code == 0, result.output
    put.assert_called_once_with("backup-storage/pilot", {"config": {**config, key: value}})


@pytest.mark.parametrize("flag,value", [("--default", True), ("--no-default", False)])
def test_storage_update_default_only_preserves_repository_and_policy(monkeypatch, flag, value):
    from cli.commands import backup_storage
    from cli.main import app

    config = {
        "engine": "restic", "restic_local_repository": "/backup/restic",
        "restic_automatic_maintenance": False, "restic_offsite_prune_qualified": True,
    }
    monkeypatch.setattr(backup_storage, "_api_get", lambda _: {"config": config})
    put = MagicMock(return_value={"id": "pilot"})
    monkeypatch.setattr(backup_storage, "_api_put", put)

    result = runner.invoke(app, ["backup", "storage", "update", "pilot", flag])

    assert result.exit_code == 0, result.output
    put.assert_called_once_with("backup-storage/pilot", {"config": config, "is_default": value})


@pytest.mark.parametrize("command,tail,path,method", [
    ("initialize", [], "backup-storage/pilot/initialize?local_only=false", "_api_post"),
    ("initialize", ["--local-only"], "backup-storage/pilot/initialize?local_only=true", "_api_post"),
    ("status", [], "backup-storage/pilot/repository", "_api_get"),
    ("maintenance", [], "backup-storage/pilot/maintenance?dry_run=true", "_api_post"),
    ("maintenance", ["--preview"], "backup-storage/pilot/maintenance?dry_run=true", "_api_post"),
    ("maintenance", ["--apply"], "backup-storage/pilot/maintenance?dry_run=false", "_api_post"),
    ("maintenance", ["--force-critical-restore"], "backup-storage/pilot/maintenance?dry_run=true&force_critical_restore=true", "_api_post"),
    ("maintenance", ["--apply", "--force-critical-restore"], "backup-storage/pilot/maintenance?dry_run=false&force_critical_restore=true", "_api_post"),
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


@pytest.mark.parametrize("command,tail,method,path", [
    ("status", [], "_api_get", "backup-storage/pilot/repository"),
    ("maintenance", [], "_api_post", "backup-storage/pilot/maintenance?dry_run=true"),
    ("maintenance", ["--apply"], "_api_post", "backup-storage/pilot/maintenance?dry_run=false"),
])
def test_repository_routine_output_omits_large_journals_and_details_preserves_full_response(monkeypatch, command, tail, method, path):
    from cli.commands import backup_storage
    from cli.main import app

    journal = {"verified_objects": {f"data/{i:05d}": {"sha256": "a" * 64, "size": i} for i in range(20000)},
               "pending_objects": {f"data/{i:05d}": "ROOT_OBJECT_JOURNAL_SENTINEL" for i in range(20000)}}
    maintenance = {
        "status": "completed", "dry_run": command == "maintenance" and not tail,
        "summary": {"result": "completed", "reclaimed_bytes": 123456, "free_bytes": {"local": 7654321, "remote": None},
                    "blockers": ["remote"], "evidence": "/fixture/private/state.json"},
        "local": {"monthly": {"status": "verified", "verified": True, "state": journal},
                  "retention": {"status": "completed", "keep_ids": ["b" * 64] * 34},
                  "prune": {"status": "completed", "physical_bytes_confirmed": True, "state": journal}},
        "remote": {"prune": {"status": "skipped", "reason": "insufficient-headroom", "state": journal}},
    }
    payload = maintenance if command == "maintenance" else {
        "ready": True, "engine": "restic", "prune_qualified": True, "cutover_qualified": False,
        "sources": {str(i): {"snapshot_id": "b" * 64, "completed_at": "2026-10-05T12:00:00+00:00"} for i in range(34)},
        "offsite": {"status": "pending", "pending_snapshot_ids": ["b" * 64] * 9, "pending_objects": journal["pending_objects"], "mismatches": ["fixture-mismatch"]},
        "maintenance": {"last_run_at": "2026-10-05T12:00:00+00:00", "result": maintenance},
    }
    original = json.dumps(payload, sort_keys=True)
    request = MagicMock(return_value=payload)
    monkeypatch.setattr(backup_storage, method, request)
    args = ["backup", "storage", command, "pilot", *tail]
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    assert len(result.output) < 6000
    assert "ROOT_OBJECT_JOURNAL_SENTINEL" not in result.output
    assert "verified_objects" not in result.output
    concise = json.loads(result.output)
    summary = concise if command == "maintenance" else concise["maintenance"]
    assert summary["result"] == "completed"
    assert summary["reclaimed_bytes"] == 123456
    assert summary["free_bytes"] == {"local": 7654321, "remote": None}
    assert summary["evidence"] == "/fixture/private/state.json"
    assert summary["blockers"] == [{"repository": "remote", "operation": "prune", "status": "skipped", "reason": "insufficient-headroom"}]
    assert concise["details_command"] == "st backup storage status pilot --details"
    if command == "status":
        assert concise["source_count"] == 34
        assert concise["offsite"]["pending_snapshot_count"] == 9
        assert concise["offsite"]["pending_object_count"] == 20000
        assert concise["offsite"]["mismatch_count"] == 1
        assert concise["maintenance"]["last_run_at"] == "2026-10-05T12:00:00+00:00"
    request.assert_called_once_with(path, **({"timeout": backup_storage.LONG_RUNNING_TIMEOUT} if method == "_api_post" else {}))
    request.reset_mock()
    full = runner.invoke(app, [*args, "--details"])
    assert full.exit_code == 0
    assert json.loads(full.output) == payload
    assert "ROOT_OBJECT_JOURNAL_SENTINEL" in full.output
    assert json.dumps(payload, sort_keys=True) == original
    request.assert_called_once_with(path, **({"timeout": backup_storage.LONG_RUNNING_TIMEOUT} if method == "_api_post" else {}))


def test_repository_summary_preserves_readiness_and_maintenance_failures(monkeypatch):
    from cli.commands import backup_storage
    from cli.main import app

    monkeypatch.setattr(backup_storage, "_api_get", lambda _: {"ready": False, "engine": "restic", "error": "fixture missing credential"})
    status = runner.invoke(app, ["backup", "storage", "status", "pilot"])
    assert status.exit_code == 0
    assert json.loads(status.output)["ready"] is False
    assert json.loads(status.output)["error"] == "fixture missing credential"
    monkeypatch.setattr(backup_storage, "_api_post", lambda *_, **__: {
        "status": "failed", "dry_run": True,
        "local": {"monthly": {"verified": False, "status": "failed", "error": "fixture integrity error"}},
        "critical_restore": {"status": "failed", "failed_source": "database", "error": "fixture restore error"},
    })
    result = runner.invoke(app, ["backup", "storage", "maintenance", "pilot"])
    assert result.exit_code == 0
    summary = json.loads(result.output)
    assert summary["result"] == "failed"
    assert summary["reclaimed_bytes"] is None
    assert summary["free_bytes"] == {"local": None, "remote": None}
    assert [blocker["error"] for blocker in summary["blockers"]] == ["fixture integrity error", "fixture restore error"]


@pytest.mark.parametrize("format_args", [["--no-compact"], ["--no-compact", "--human"]])
def test_repository_json_modes_still_require_details_for_full_journal(monkeypatch, format_args):
    from cli.commands import backup_storage
    from cli.main import app

    payload = {"ready": True, "maintenance": {"result": {"local": {"prune": {"state": {"sentinel": "FULL_JOURNAL" * 20000}}}}}}
    monkeypatch.setattr(backup_storage, "_api_get", lambda _: payload)
    args = [*format_args, "backup", "storage", "status", "pilot"]
    concise = runner.invoke(app, args)
    assert concise.exit_code == 0
    assert json.loads(concise.output)["ready"] is True
    assert len(concise.output) < 3000
    assert "FULL_JOURNAL" not in concise.output
    details = runner.invoke(app, [*args, "--details"])
    assert details.exit_code == 0
    assert json.loads(details.output) == payload


@pytest.mark.parametrize("frequency", ["hourly", "four_hourly", "daily", "weekly", "monthly"])
def test_schedule_accepts_supported_frequency_and_preserves_other_fields(monkeypatch, frequency):
    from cli.commands import backup
    from cli.main import app

    update = MagicMock(return_value={"enabled": True, "frequency": frequency, "retention_days": 37})
    monkeypatch.setattr(backup, "_get_source_api", lambda: SimpleNamespace(update_source=update))
    result = runner.invoke(app, ["backup", "schedule", "source", "--frequency", frequency])
    assert result.exit_code == 0, result.output
    update.assert_called_once_with("source", enabled=None, frequency=frequency, retention_days=None)


def test_schedule_help_lists_four_hourly_and_unknown_frequency_fails_before_api(monkeypatch):
    from cli.commands import backup
    from cli.main import app

    help_result = runner.invoke(app, ["backup", "schedule", "--help"])
    assert help_result.exit_code == 0
    assert "hourly, four_hourly, daily, weekly, monthly" in help_result.output
    get_api = MagicMock(side_effect=AssertionError("invalid frequency must not contact API"))
    monkeypatch.setattr(backup, "_get_source_api", get_api)
    result = runner.invoke(app, ["backup", "schedule", "source", "--frequency", "every-four-hours"])
    assert result.exit_code == 2
    assert "four_hourly" in result.output
    get_api.assert_not_called()
