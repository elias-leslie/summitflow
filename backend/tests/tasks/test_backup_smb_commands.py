"""SMB grammar and transfer boundaries, with no network invocation."""
import stat
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from app.tasks import backup_native_smb as native
from app.tasks import backup_restore_drill, backup_restore_test
from app.utils.smb_commands import (
    SmbCommandError,
    smb_archive_location,
    smb_command,
    smb_path,
    smb_service,
)


@pytest.mark.parametrize("value", ["name;separator", 'name"quote', "name'quote", "name\\escape", "name\nline", "name\x00null", "name*glob", "name?glob", "../other", "a/../other", "a/.. /other", "a/dot./other", "a//b", "a" * 256, "a/" * 600])
def test_unsafe_tokens_are_refused_without_echoing_input(value):
    with pytest.raises(SmbCommandError) as exc:
        smb_command(("cd", value), ("ls",))
    assert value not in str(exc.value)


def test_fixed_grammar_preserves_spaces_unicode_root_and_archive_suffix():
    assert smb_command(("cd", "Team Backups/équipe"), ("put", "/tmp/local archive.age", "archive.age"), ("ls", "archive.age")) == 'cd "Team Backups/équipe"; put "/tmp/local archive.age" "archive.age"; ls "archive.age"'
    assert smb_service("[::1]", "Backups$") == "//[::1]/Backups$"
    assert smb_archive_location("//host/share/archive.age") == ("//host/share", ".", "archive.age")
    assert smb_path("/") == "/"


@pytest.mark.parametrize("commands", [("arbitrary",), ("cd",), ("ls", "a", "b"), ("put", "local", "nested/file"), ("get", "../file", "/tmp/file")])
def test_builder_limits_operations_and_remote_file_scope(commands):
    with pytest.raises(SmbCommandError):
        smb_command(commands)


@pytest.mark.parametrize("field,value", [("remote_path", "backups;separator"), ("host", "host/share"), ("share", "../share"), ("archive", "../archive.age"), ("local", "local;separator.age")])
def test_upload_refuses_invalid_configuration_before_any_subprocess(tmp_path, monkeypatch, field, value):
    storage = native.StorageConfig("host", "share", "backups", "user", tmp_path / "credentials")
    options = dict(storage.__dict__)
    if field in options:
        options[field] = value
    runner = Mock(side_effect=AssertionError("no transfer allowed"))
    monkeypatch.setattr(native.subprocess, "run", runner)
    monkeypatch.setattr(native, "run_bulk_process", runner)
    result = native._smb_upload(tmp_path / (value if field == "local" else "archive.age"), value if field == "archive" else "archive.age", native.StorageConfig(**options))
    assert not result.ok
    assert runner.call_count == 0
    assert result.error is not None
    assert value not in result.error


@pytest.mark.parametrize("module,name", [(backup_restore_test, "_download_smb_archive"), (backup_restore_drill, "_download_from_smb")])
@pytest.mark.parametrize("location", ["//host/share/backups;separator/archive.age", "//host/share/backups/..", "//host/share/backups/file*", "not-smb", "//host/share/backups/file\nline"])
def test_restore_rejects_invalid_locations_before_temp_creation(module, name, location, monkeypatch):
    import tempfile
    monkeypatch.setattr(tempfile, "mkdtemp", Mock(side_effect=AssertionError("no local target")))
    monkeypatch.setattr(module.subprocess, "run", Mock(side_effect=AssertionError("no network")))
    assert getattr(module, name)(location) is None


@pytest.mark.parametrize("module,name", [(backup_restore_test, "_download_smb_archive"), (backup_restore_drill, "_download_from_smb")])
@pytest.mark.parametrize("success", [True, False])
def test_restore_preserves_spaces_and_cleans_failed_download(module, name, success, monkeypatch, tmp_path, backup_job_scratch):
    import tempfile
    directory = backup_job_scratch / "download directory"
    directory.mkdir(mode=0o700)
    monkeypatch.setattr(tempfile, "mkdtemp", lambda **_: str(directory))
    def run(args, **kwargs):
        assert args[-1] == f'cd "Team Backups"; get "archive file.age" "{directory}/archive file.age"'
        assert kwargs["timeout"] == 300
        if success:
            (directory / "archive file.age").touch()
        return subprocess.CompletedProcess(args, 0 if success else 1, "", "")
    monkeypatch.setattr(module, "run_bulk_process", run, raising=False)
    monkeypatch.setattr(module.subprocess, "run", run)
    result = getattr(module, name)("//host/share/Team Backups/archive file.age")
    assert bool(result) is success
    assert directory.exists() is success


def test_credentials_are_private_from_creation_and_replace_symlink(monkeypatch, tmp_path):
    from app.api.backups import storage_endpoints as api
    outside = tmp_path / "outside"
    outside.write_text("unchanged")
    (tmp_path / ".smbcredentials").symlink_to(outside)
    monkeypatch.setattr(api, "CREDENTIALS_DIR", tmp_path)
    original_replace = api.os.replace
    def replace(source, target):
        assert stat.S_IMODE(Path(source).stat().st_mode) == 0o600
        assert outside.read_text() == "unchanged"
        original_replace(source, target)
    monkeypatch.setattr(api.os, "replace", replace)
    path = Path(api._write_smb_credentials("user", "fixture-password"))
    assert not path.is_symlink()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert outside.read_text() == "unchanged"
    assert list(tmp_path.glob(".smbcredentials-*")) == []


def test_configuration_validation_rejects_unsupported_smb_path():
    from app.api.backups.storage_endpoints import _validate_engine_config
    with pytest.raises(HTTPException) as exc:
        _validate_engine_config({"host": "host", "share": "share", "path": "backups;separator"}, "smb")
    assert exc.value.status_code == 400


def test_directory_creation_quotes_each_cumulative_path(monkeypatch, tmp_path):
    storage = native.StorageConfig("host", "share", "Team Backups/project", "user", tmp_path / "credentials")
    commands = []
    def run(args, **kwargs):
        commands.append(args[-1])
        return subprocess.CompletedProcess(args, 1 if len(commands) == 1 else 0, "", "")
    monkeypatch.setattr(native.subprocess, "run", run)
    assert native._ensure_smb_dir(storage).ok
    assert commands == ['cd "Team Backups/project"; ls', 'mkdir "Team Backups"', 'mkdir "Team Backups/project"', 'cd "Team Backups/project"; ls']


def test_probe_validates_full_path_even_when_only_probing_parent(monkeypatch, tmp_path):
    credentials = tmp_path / "credentials"
    credentials.touch()
    storage = native.StorageConfig("host", "share", "backups/invalid;name", "user", credentials)
    monkeypatch.setattr(native.shutil, "which", lambda _: "smbclient")
    monkeypatch.setattr(native.subprocess, "run", Mock(side_effect=AssertionError("invalid full path")))
    assert not native._smb_available(storage)


def test_pending_archive_name_cannot_escape_directory(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    storage = native.StorageConfig("host", "share", "backups", "user", tmp_path / "credentials")
    with pytest.raises(SmbCommandError):
        native._save_pending(tmp_path / "source", "../archive.age", "project", storage)
    assert not (tmp_path / ".local").exists()


def test_failed_credential_replace_cleans_private_tempfile(monkeypatch, tmp_path):
    from app.api.backups import storage_endpoints as api
    target = tmp_path / ".smbcredentials"
    target.write_text("old")
    monkeypatch.setattr(api, "CREDENTIALS_DIR", tmp_path)
    monkeypatch.setattr(api.os, "replace", Mock(side_effect=OSError("fixture failure")))
    with pytest.raises(OSError):
        api._write_smb_credentials("user", "fixture-password")
    assert target.read_text() == "old"
    assert list(tmp_path.glob(".smbcredentials-*")) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("path,valid", [("Team Backups", True), ("backups;separator", False)])
async def test_storage_probe_uses_shared_grammar(monkeypatch, tmp_path, path, valid):
    from app.api.backups import storage_endpoints as api
    credentials = tmp_path / "credentials"
    credentials.touch()
    backend = {"backend_type": "smb", "config": {"host": "host", "share": "share", "path": path, "credentials_file": str(credentials)}}
    monkeypatch.setattr(api.backup_store, "get_backend", lambda _: backend)
    monkeypatch.setattr(api.backup_store, "update_test_result", Mock())
    monkeypatch.setattr(api, "get_backup_key_status", lambda: {"ready": True})
    runner = Mock(return_value=subprocess.CompletedProcess([], 0, "", ""))
    monkeypatch.setattr(api.safe_subprocess, "run", runner)
    result = await api.test_storage_backend("fixture")
    assert result["local_success"] is valid
    assert runner.call_count == int(valid)
    if valid:
        assert runner.call_args.args[0][-1] == 'cd "Team Backups"; ls'
