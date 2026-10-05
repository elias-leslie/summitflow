"""Integration regressions using bounded synthetic repositories, never Drive."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from app.tasks import backup_repository_runtime as runtime
from app.tasks.backup_restic import ResticAdapter, ResticConfig, ResticError


@pytest.fixture
def repository_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    monkeypatch.setenv("SF_HOST_RETENTION_PRESSURE_MIN_FREE_GB", "0")
    keys = tmp_path / "keys"
    keys.mkdir(mode=0o700)
    monkeypatch.setattr(runtime, "backup_key_directory", lambda: keys)
    monkeypatch.setattr(runtime.backup_store, "list_backups", lambda **_: ([], 0))
    monkeypatch.setattr(runtime.backup_store, "list_backends", lambda **_: [])
    for name in ("local-password", "remote-password"):
        (keys / name).touch(mode=0o600)
        (keys / name).write_text(f"synthetic-fixture-{name}\n")
    return {
        "BACKUP_ENGINE": "restic", "BACKUP_STORAGE_BACKEND_ID": "stb-fixture",
        "RESTIC_LOCAL_REPOSITORY": str(tmp_path / "local"),
        "RESTIC_REMOTE_REPOSITORY": str(tmp_path / "remote"),
        "RESTIC_LOCAL_PASSWORD_FILE": str(keys / "local-password"),
        "RESTIC_REMOTE_PASSWORD_FILE": str(keys / "remote-password"),
        "RESTIC_KEY_DIRECTORY": str(keys), "RESTIC_HOSTNAME": "fixture",
    }


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def test_atomic_checkpoint_permissions_and_symlinks(repository_env: dict[str, str], tmp_path: Path) -> None:
    config = ResticConfig.from_env(repository_env)
    with runtime._checkpoint(config) as (directory, state):
        state["sources"]["fixture"] = {"snapshot_id": "a" * 64}
        runtime._save_json(directory / "state.json", state)
        assert (directory / "state.json").stat().st_mode & 0o777 == 0o600
    with runtime._checkpoint(config) as (_, state):
        assert state["sources"]["fixture"]["snapshot_id"] == "a" * 64
    unsafe = tmp_path / "unsafe.json"
    unsafe.symlink_to(directory / "state.json")
    with pytest.raises(ResticError, match="private regular file"):
        runtime._load_json(unsafe)


def test_sql_failure_leaves_durable_local_reference_and_no_plaintext(repository_env: dict[str, str], tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "work.txt").write_text("unsaved work")
    config = ResticConfig.from_env(repository_env)
    saved = {"snapshot_id": "a" * 64, "repository_id": "b" * 64, "location": "restic-v1:fixture", "verification": {"verified": True, "capture": {}}}
    with patch.object(runtime, "canonical_backup_source_roots", return_value={}), patch.object(ResticAdapter, "save_payload", return_value=saved), patch.object(runtime, "record_local_archive", side_effect=RuntimeError("SQL unavailable")), pytest.raises(RuntimeError, match="SQL unavailable"):
        runtime.run_repository_backup(project_dir=str(source), source_id="fixture", env=repository_env)
    with runtime._checkpoint(config) as (directory, state):
        assert state["sources"]["fixture"]["snapshot_id"] == "a" * 64
        assert not any((directory / "payloads").iterdir())


def test_recorded_backend_required_no_current_default_fallback() -> None:
    with pytest.raises(ResticError, match="default fallback refused"):
        runtime._backup_environment({"source_id": "fixture", "verification_json": {"format": "restic-v1"}})


def test_codex_essentials_does_not_download_previous_git_bundle(repository_env: dict[str, str], tmp_path: Path) -> None:
    source = tmp_path / ".codex"
    source.mkdir()
    (source / "AGENTS.md").write_text("custom instructions")
    saved = {"snapshot_id": "a" * 64, "repository_id": "b" * 64, "location": "restic-v1:fixture", "verification": {"verified": True, "capture": {}}}
    with (
        patch.object(runtime, "canonical_backup_source_roots", return_value={}),
        patch.object(runtime, "_previous_bundle", side_effect=AssertionError("unnecessary previous bundle download")),
        patch.object(ResticAdapter, "save_payload", return_value=saved) as save,
        patch.object(runtime, "record_local_archive"),
    ):
        runtime.run_repository_backup(project_dir=str(source), source_id=".codex", env=repository_env, local_only=True)
    assert save.call_args.args[1]["recovery"]["capture_profile"] == "codex-restore-essentials-v1"
    assert save.call_args.args[1]["recovery"]["git"] is None


def test_infrastructure_capture_uses_stable_host_config_root(repository_env, tmp_path) -> None:
    release = tmp_path / "immutable-release"
    release.mkdir()
    host = tmp_path / "stable-host"
    (host / "docker/compose/hatchet-config").mkdir(parents=True)
    (host / "docker/compose/.env").write_text("SYNTHETIC_CONFIG=fixture\n")
    snapshot = tmp_path / "fixture-payload"
    snapshot.mkdir(mode=0o700)
    payload = {"snapshot_dir": snapshot, "total_files": 1, "db_bytes": 1, "recovery": {}, "db_dump_name": "pgdumpall.sql"}
    saved = {"snapshot_id": "a" * 64, "repository_id": "b" * 64, "location": "restic-v1:fixture", "verification": {"verified": True, "capture": {}}}
    with (
        patch.object(runtime, "get_host_config_root", return_value=host),
        patch.object(runtime, "prepare_infrastructure_payload", return_value=payload) as prepare,
        patch.object(ResticAdapter, "save_payload", return_value=saved),
        patch.object(runtime, "record_local_archive"),
    ):
        runtime.run_repository_backup(project_dir=str(release), source_id="infrastructure", env=repository_env, local_only=True, infrastructure=True)
    assert prepare.call_args.args[0] == release
    assert prepare.call_args.kwargs["host_config_root"] == host
    assert not (release / "docker/compose/.env").exists()


def test_initialization_never_overwrites_existing_password(repository_env: dict[str, str]) -> None:
    password = Path(repository_env["RESTIC_LOCAL_PASSWORD_FILE"])
    before = password.stat()
    with patch.object(ResticAdapter, "readiness", return_value={"ready": True}), patch.object(ResticAdapter, "initialize", return_value={"status": "initialized"}):
        result = runtime.initialize_repository(repository_env, local_only=True)
    assert password.stat().st_mtime_ns == before.st_mtime_ns
    assert result["default_changed"] is False
    assert result["recovery_key_escrow_confirmed"] is False


@pytest.mark.skipif(shutil.which("restic") is None, reason="Pinned Restic binary not installed")
def test_real_independent_copy_deduplicates_and_recovers_wip(repository_env: dict[str, str], tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    # Large enough to demonstrate unchanged payload dedup, but only a tiny
    # synthetic fixture; no real conversations or credentials are captured.
    (source / "asset.bin").write_bytes(os.urandom(8 * 1024 * 1024))
    (source / "work.txt").write_text("committed\n")
    _git(source, "init", "-q")
    _git(source, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "add", ".")
    _git(source, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "fixture")
    (source / "work.txt").write_text("staged\n")
    _git(source, "add", "work.txt")
    (source / "work.txt").write_text("working copy\n")
    runtime.initialize_repository(repository_env)
    with patch.object(runtime, "canonical_backup_source_roots", return_value={}):
        first = runtime.run_repository_backup(project_dir=str(source), source_id="fixture", env=repository_env)
        second = runtime.run_repository_backup(project_dir=str(source), source_id="fixture", env=repository_env)
    assert first["verification"]["offsite"]["status"] == "verified"
    assert second["verification"]["offsite"]["status"] == "verified"
    assert second["unchanged"] is True
    assert first["verification"]["repository_id"] != first["verification"]["remote_repository_id"]
    assert second["data_added_bytes"] < first["data_added_bytes"] / 2
    assert second["verification"]["offsite"]["new_object_bytes"] < first["verification"]["offsite"]["new_object_bytes"] / 2
    backup = {"source_id": "fixture", "storage_backend_id": "stb-fixture", "verification_json": second["verification"]}
    with patch.object(runtime, "build_storage_env", return_value=repository_env), runtime.materialize_repository_archive(backup, remote=True) as archive:
        from app.tasks.backup_native_restore import restore_isolated_archive

        restored = restore_isolated_archive(archive, tmp_path / "recovered")
    assert restored["recovery"]["git_restored"] is True
    assert (tmp_path / "recovered" / "work.txt").read_text() == "working copy\n"
    staged = subprocess.run(["git", "-C", str(tmp_path / "recovered"), "show", ":work.txt"], capture_output=True, text=True, check=True)
    assert staged.stdout == "staged\n"
    with runtime._checkpoint(ResticConfig.from_env(repository_env)) as (directory, state):
        assert state["offsite"]["pending_objects"] == []
        assert not any((directory / "payloads").iterdir())
        # The private journal contains references, never password contents.
        assert "synthetic-fixture-local-password" not in json.dumps(state)


@pytest.mark.skipif(shutil.which("restic") is None, reason="Pinned Restic binary not installed")
def test_real_serial_batch_checks_copies_once_and_retries_all_pending(repository_env, tmp_path, monkeypatch):
    runtime.initialize_repository(repository_env)
    monkeypatch.setattr(runtime, "canonical_backup_source_roots", lambda: {})
    sources = [tmp_path / "source-one", tmp_path / "source-two"]
    for source in sources:
        source.mkdir()
        (source / "saved.txt").write_text(source.name)
    config = ResticConfig.from_env(repository_env)
    with patch.object(ResticAdapter, "check", wraps=ResticAdapter(config).check) as checked, patch.object(ResticAdapter, "sync", wraps=ResticAdapter(config).sync) as copied:
        with runtime.repository_capture_batch() as batch:
            first = runtime.run_repository_backup(project_dir=str(sources[0]), source_id="one", env=repository_env)
            second = runtime.run_repository_backup(project_dir=str(sources[1]), source_id="two", env=repository_env)
            assert first["verification"]["structural_check_pending"] is True
            assert first["verification"]["structural_check_at"] is None
            with runtime._checkpoint(config) as (directory, state):
                assert not any((directory / "payloads").iterdir())
                assert state["offsite"]["pending_snapshot_ids"] == [first["snapshot_id"], second["snapshot_id"]]
        checked.assert_not_called()
        copied.assert_not_called()
        with patch.object(ResticAdapter, "sync", side_effect=ResticError("synthetic unavailable offsite")) as unavailable:
            failed = runtime.sync_repository_batch(batch)
            assert next(iter(failed.values()))["status"] == "pending"
            assert unavailable.call_count == 1
        with runtime._checkpoint(config) as (_, state):
            assert state["offsite"]["pending_snapshot_ids"] == [first["snapshot_id"], second["snapshot_id"]]
            assert all(value["result"]["verification"]["offsite"]["status"] == "pending" for value in state["sources"].values())
        results = runtime.sync_repository_batch(batch)
        assert next(iter(results.values()))["status"] == "verified"
        assert checked.call_count == copied.call_count == 1
    with runtime._checkpoint(config) as (_, state):
        assert state["offsite"]["pending_snapshot_ids"] == []
        assert all(value["result"]["verification"]["offsite"]["status"] == "verified" for value in state["sources"].values())
        assert all(value["result"]["verification"]["structural_check_pending"] is False for value in state["sources"].values())
    # Restart retry is independent of newly due captures and includes every
    # retained SQL snapshot, even when checkpoint sources contain newer points.
    old = first["snapshot_id"]
    rows = [{"id": "old-row", "storage_backend_id": "stb-fixture", "status": "completed_pending_upload", "verification_json": {"format": "restic-v1", "repository_id": first["repository_id"], "snapshot_id": old, "offsite": {"status": "pending"}}}]
    monkeypatch.setattr(runtime.backup_store, "list_backups", lambda **_: (rows, 1))
    merged = []
    monkeypatch.setattr(runtime.backup_store, "merge_backup_verification_json", lambda backup_id, update: merged.append((backup_id, update)))
    monkeypatch.setattr(runtime.backup_store, "update_backup_status", lambda *args: None)
    results = runtime.sync_repository_batch(batch)
    assert next(iter(results.values()))["status"] == "verified"
    assert merged[0][0] == "old-row"
    assert merged[0][1]["offsite"]["status"] == "verified"


def test_database_capture_never_reuses_unchanged_files(repository_env, tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    dumped = []
    def dump(project_name, destination, env):
        dumped.append(project_name)
        destination.write_bytes(b"consistent fresh SQL")
        return destination.stat().st_size, True
    monkeypatch.setattr("app.tasks.backup_native_archive._dump_database", dump)
    monkeypatch.setattr(runtime, "canonical_backup_source_roots", lambda: {})
    saved = {"snapshot_id": "a" * 64, "repository_id": "b" * 64, "location": "restic-v1:fixture", "verification": {"verified": True, "capture": {}}}
    (source / "saved.txt").write_text("unchanged files")
    with patch.object(ResticAdapter, "save_payload", side_effect=lambda *_args: json.loads(json.dumps(saved))) as save, patch.object(runtime, "record_local_archive"):
        runtime.run_repository_backup(project_dir=str(source), source_id="source", env=repository_env, local_only=True)
        runtime.run_repository_backup(project_dir=str(source), source_id="source", env=repository_env, local_only=True)
    assert len(dumped) == save.call_count == 2


def test_sqlite_capture_never_reuses_unchanged_database(repository_env, tmp_path, monkeypatch):
    from app.tasks import backup_native_recovery as recovery

    source = tmp_path / "source"
    source.mkdir()
    with sqlite3.connect(source / "records.sqlite") as connection:
        connection.execute("CREATE TABLE fixture (value TEXT)")
        connection.execute("INSERT INTO fixture VALUES ('durable')")
    monkeypatch.setattr(runtime, "canonical_backup_source_roots", lambda: {})
    monkeypatch.setattr("app.tasks.backup_native_archive._dump_database", lambda *_: (0, False))
    saved = {"snapshot_id": "a" * 64, "repository_id": "b" * 64, "location": "restic-v1:fixture", "verification": {"verified": True, "capture": {}}}
    with patch.object(recovery, "_copy_sqlite_database", wraps=recovery._copy_sqlite_database) as capture, patch.object(ResticAdapter, "save_payload", side_effect=lambda *_args: json.loads(json.dumps(saved))) as save, patch.object(runtime, "record_local_archive"):
        runtime.run_repository_backup(project_dir=str(source), source_id="source", env=repository_env, local_only=True)
        runtime.run_repository_backup(project_dir=str(source), source_id="source", env=repository_env, local_only=True)
    assert capture.call_count == save.call_count == 2
