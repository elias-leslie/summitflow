"""Integration regressions using bounded synthetic repositories, never Drive."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from app.tasks import backup_repository_runtime as runtime
from app.tasks.backup_restic import ResticAdapter, ResticConfig, ResticError


@pytest.fixture
def repository_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    keys = tmp_path / "keys"
    keys.mkdir(mode=0o700)
    monkeypatch.setattr(runtime, "backup_key_directory", lambda: keys)
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
