"""Restic interface tests: no installed binaries, account access, or real expiry."""

from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, TypedDict

import pytest

from app.tasks import backup_restic as engine

LOCAL = "1" * 64
REMOTE = "2" * 64
SNAPSHOT = "3" * 64


class RetentionSnapshot(TypedDict):
    id: str
    tags: list[str]
    time: str


class FakeProcess:
    """Native-command fixture preserving destination encrypted object semantics."""

    def __init__(self, payload: Path) -> None:
        self.payload = payload
        self.commands: list[list[str]] = []
        self.objects: dict[str, bytes] = {}
        self.local_snapshots: list[dict[str, Any]] = []
        self.remote_snapshots: list[dict[str, Any]] = []
        self.copy_failure: int | None = None
        self.cancel_copy = False
        self.bad_hashes: set[str] = set()
        self.missing_hashes: set[str] = set()
        self.changed_identity: set[str] = set()
        self.fail_check = False
        self.check_failure: int | None = None
        self.remote_unavailable = False
        self.added = 10
        self.init_missing: set[str] = set()
        self.last_environment: dict[str, str] = {}

    def add_object(self, content: bytes, kind: str = "data") -> str:
        digest = hashlib.sha256(content).hexdigest()
        path = f"data/{digest[:2]}/{digest}" if kind == "data" else f"{kind}/{digest}"
        self.objects[path] = content
        return path

    def entry(self, path: str, *, hashed: bool = False) -> dict[str, Any]:
        value: dict[str, Any] = {"Path": path, "Name": Path(path).name, "ID": "storage:" + path, "Size": len(self.objects[path]), "IsDir": False}
        if hashed:
            if path in self.changed_identity:
                value["ID"] += ":replacement"
            if path not in self.missing_hashes:
                value["Hashes"] = {"SHA-256": "0" * 64 if path in self.bad_hashes else Path(path).name}
        return value

    def __call__(self, command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.commands.append(command)
        self.last_environment = kwargs["env"]
        stdout: Any = ""
        code = 0
        if command[:2] == ["restic", "version"]:
            stdout = f"restic {engine.RESTIC_VERSION} compiled with go"
        elif command[:2] == ["rclone", "version"]:
            stdout = f"rclone v{engine.RCLONE_VERSION}\n"
        elif command[:2] == ["rclone", "lsjson"]:
            if "--stat" in command:
                path = command[2].removeprefix("fixture:repository/")
                stdout = json.dumps(self.entry(path, hashed="--hash-type" in command))
            else:
                stdout = json.dumps([self.entry(path) for path in self.objects])
        elif command[:2] == ["rclone", "cat"]:
            path = command[2].removeprefix("fixture:repository/")
            kwargs["stdout_sink"](io.BytesIO(self.objects[path]))
        elif command[:2] == ["rclone", "about"]:
            stdout = json.dumps({"total": 1000000, "free": 500000})
        elif command[0] == "restic":
            remote = command[command.index("--repo") + 1].startswith("rclone:")
            if "cat" in command:
                repo = REMOTE if remote else LOCAL
                if repo in self.init_missing or (remote and self.remote_unavailable):
                    code = 10 if repo in self.init_missing else 1
                else:
                    stdout = json.dumps({"id": repo, "version": 2, "chunker_polynomial": "fixture"})
            elif "init" in command:
                self.init_missing.discard(REMOTE if remote else LOCAL)
                stdout = "{}"
            elif "snapshots" in command:
                values = self.remote_snapshots if remote else self.local_snapshots
                if "--tag" in command:
                    tag = command[command.index("--tag") + 1]
                    values = [value for value in values if tag in value["tags"]]
                stdout = json.dumps(values)
            elif "backup" in command:
                snapshot_id = SNAPSHOT if not self.local_snapshots else "4" * 64
                tag = command[command.index("--tag") + 1]
                self.local_snapshots.append({"id": snapshot_id, "tags": [tag], "paths": [str(self.payload)], "hostname": "fixture-host", "time": "2026-09-29T12:00:00Z"})
                stdout = json.dumps({"message_type": "summary", "snapshot_id": snapshot_id, "total_bytes_processed": 25, "data_added": self.added, "data_added_packed": self.added // 2})
            elif "copy" in command:
                self.add_object(b"encrypted-pack")
                remote_path = self.add_object(b"encrypted-snapshot", "snapshots")
                sources = command[command.index("--from-password-file") + 2:]
                for source in sources:
                    if not any(value.get("original") == source for value in self.remote_snapshots):
                        self.remote_snapshots.append({"id": Path(remote_path).name, "original": source, "paths": [str(self.payload)], "tags": ["source:fixture"], "time": "2026-09-29T12:00:00Z"})
                if self.cancel_copy:
                    raise engine.BackupCancelled("fixture cancellation")
                code = self.copy_failure or 0
            elif "check" in command:
                code = self.check_failure or (1 if self.fail_check else 0)
                stdout = "{}"
            elif "restore" in command:
                destination = Path(command[command.index("--target") + 1])
                materialized = destination / self.payload.relative_to("/")
                materialized.mkdir(parents=True)
                (materialized / "fixture.sql").write_bytes(b"validated")
                if "--include" in command:
                    included = Path(command[command.index("--include") + 1]).relative_to(self.payload)
                    recovery_file = materialized / included
                    recovery_file.parent.mkdir(parents=True, exist_ok=True)
                    recovery_file.write_bytes(b"verified recovery fixture")
                stdout = "{}"
            elif "forget" in command or "prune" in command:
                stdout = "{}"
            else:
                raise AssertionError(command)
        else:
            raise AssertionError(command)
        return subprocess.CompletedProcess(command, code, stdout, "untrusted credential-like diagnostics")


@pytest.fixture
def setup(tmp_path: Path, monkeypatch):
    from app.utils import transient_scratch

    scratch = tmp_path / "scratch"
    scratch.mkdir(mode=0o700)
    monkeypatch.setattr(transient_scratch, "SCRATCH_ROOT", scratch)
    real_is_mount = Path.is_mount
    monkeypatch.setattr(Path, "is_mount", lambda path: path == scratch or real_is_mount(path))
    keys = tmp_path / "keys"
    keys.mkdir(mode=0o700)
    for name in ("local-password", "remote-password", "rclone.conf"):
        path = keys / name
        path.write_bytes(b"fixture-only")
        path.chmod(0o600)
    payload = tmp_path / "stable-payload"
    payload.mkdir(mode=0o700)
    (payload / "fixture.sql").write_bytes(b"fixture sql")
    config = engine.ResticConfig(
        local_repository=tmp_path / "repositories/local",
        local_password_file=keys / "local-password", key_directory=keys,
        remote_repository="rclone:fixture:repository",
        remote_password_file=keys / "remote-password", rclone_config=keys / "rclone.conf",
        lock_directory=tmp_path / "locks", hostname="fixture-host",
    )
    process = FakeProcess(payload)
    return config, process, {"snapshot_dir": payload, "total_bytes": 25, "db_bytes": 11, "verification": {"verified": True}}


def _adapter(setup):
    config, process, payload = setup
    return engine.ResticAdapter(config, runner=process), process, payload


def _persisted():
    saves: list[dict[str, Any]] = []
    return saves, lambda state: saves.append(state)


@pytest.mark.parametrize("failure", [False, True])
def test_repository_commands_use_private_scratch_and_remove_child_work(setup, tmp_path, monkeypatch, failure):
    config, _, _ = setup
    observed = []
    monkeypatch.setenv("TMPDIR", "/tmp")
    monkeypatch.setenv("RESTIC_PASSWORD", "must-not-reach-child")

    def runner(command, **kwargs):
        env = kwargs["env"]
        temporary = Path(env["TMPDIR"])
        assert temporary.is_relative_to(tmp_path / "scratch")
        assert temporary.stat().st_mode & 0o777 == 0o700
        assert Path(env["XDG_CACHE_HOME"]).is_relative_to(tmp_path / "scratch")
        assert "RESTIC_PASSWORD" not in env
        (temporary / "fresh-check-cache").write_bytes(b"temporary fixture")
        observed.append(temporary)
        return subprocess.CompletedProcess(command, 1 if failure else 0, "{}", "")

    adapter = engine.ResticAdapter(config, runner=runner)
    if failure:
        with pytest.raises(engine.ResticError):
            adapter._run(adapter._command("check"), phase="verification")
    else:
        adapter._run(adapter._command("check"), phase="verification")
    assert observed and all(not path.exists() for path in observed)


def test_configuration_references_and_local_readiness(setup, monkeypatch):
    config, process, _ = setup
    monkeypatch.setenv("RESTIC_PASSWORD", "must-not-reach-child")
    monkeypatch.setenv("RCLONE_CONFIG_PASS", "must-not-reach-child")
    env = {"BACKUP_ENGINE": "restic", "RESTIC_LOCAL_PASSWORD_FILE": str(config.local_password_file), "RESTIC_LOCAL_REPOSITORY": str(config.local_repository)}
    parsed = engine.ResticConfig.from_env(env)
    assert parsed.local_repository == config.local_repository
    adapter = engine.ResticAdapter(parsed, runner=process)
    assert adapter.readiness(local_only=True)["ready"] is True
    assert "RESTIC_PASSWORD" not in process.last_environment
    assert "RCLONE_CONFIG_PASS" not in process.last_environment
    assert adapter.readiness()["ready"] is False
    assert not any(command[0] == "rclone" for command in process.commands)


def test_process_environment_rejects_all_inherited_remote_overrides(setup, monkeypatch):
    adapter, process, _ = _adapter(setup)
    overrides = ("RCLONE_CONFIG", "RCLONE_CONFIG_PASS", "RCLONE_PASSWORD_COMMAND", "RCLONE_CONFIG_FIXTURE_TOKEN", "RCLONE_CONFIG_FIXTURE_CLIENT_SECRET", "RCLONE_CONFIG_FIXTURE_ROOT_FOLDER_ID", "RCLONE_DRIVE_USE_TRASH", "RESTIC_PASSWORD", "RESTIC_REPOSITORY")
    for key in overrides:
        monkeypatch.setenv(key, "synthetic-environment-override")
    assert adapter.readiness()["ready"] is True
    environment = process.last_environment
    assert set(environment) & set(overrides) == {"RCLONE_CONFIG"}
    assert {key for key in environment if key.startswith("RCLONE_")} == {"RCLONE_CONFIG"}
    assert environment["RCLONE_CONFIG"] == str(adapter.config.rclone_config)
    assert not any(key.startswith("RESTIC_") for key in environment)


@pytest.mark.parametrize("kind", ["wide-mode", "symlink", "outside-keydir", "root-remote", "same-repo"])
def test_configuration_rejects_unprotected_or_unbounded_references(setup, tmp_path, kind):
    config, _, _ = setup
    if kind == "wide-mode":
        config.local_password_file.chmod(0o644)
    elif kind == "symlink":
        link = config.key_directory / "link"
        link.symlink_to(config.local_password_file)
        config = replace(config, local_password_file=link)
    elif kind == "outside-keydir":
        outside = tmp_path / "outside"
        outside.write_bytes(b"fixture")
        outside.chmod(0o600)
        config = replace(config, local_password_file=outside)
    elif kind == "root-remote":
        config = replace(config, remote_repository="rclone:fixture:/")
    else:
        config = replace(config, remote_repository=str(config.local_repository))
    with pytest.raises(engine.ResticError):
        config.validate(remote=True)


def test_initialize_independent_format_v2_shared_chunker_parameters(setup):
    adapter, process, _ = _adapter(setup)
    process.init_missing.update([LOCAL, REMOTE])
    result = adapter.initialize()
    assert result == {"local_repository_id": LOCAL, "remote_repository_id": REMOTE, "format": "restic-v1"}
    commands = [command for command in process.commands if "init" in command]
    assert len(commands) == 2
    assert "--copy-chunker-params" in commands[1]
    assert "--from-password-file" in commands[1]
    assert all("--repository-version" in command and "2" in command for command in commands)


def test_local_only_initialize_never_opens_remote(setup):
    adapter, process, _ = _adapter(setup)
    process.init_missing.add(LOCAL)
    adapter.initialize(local_only=True)
    assert not any("rclone:fixture:repository" in command or command[0] == "rclone" for command in process.commands)


@pytest.mark.parametrize("remote", [False, True])
def test_checks_use_fresh_temporary_cache_without_reusing_prior_data(setup, remote):
    adapter, process, payload = _adapter(setup)
    adapter.save_payload("fixture", payload)
    adapter.sync(SNAPSHOT, state={}, persist=lambda state: None)
    assert adapter.check(remote=remote, monthly_state={})["verified"] is True
    checks = [command for command in process.commands if "check" in command]
    assert checks
    assert any("--read-data-subset=1/30" in command for command in checks)
    assert all("--no-cache" not in command and "--with-cache" not in command for command in checks)
    assert all("--no-cache" in command for command in process.commands if command[0] == "restic" and "check" not in command)
    assert "--no-cache" in adapter._command("restore", SNAPSHOT, remote=remote)
    with pytest.raises(engine.ResticError, match="only supported for restore"):
        adapter._command("check", operation_cache=adapter.config.key_directory)


def test_save_changed_and_unchanged_snapshots_use_stable_parent_and_truthful_metrics(setup):
    adapter, process, payload = _adapter(setup)
    first = adapter.save_payload("fixture", payload)
    process.added = 0
    second = adapter.save_payload("fixture", payload)
    assert first["format"] == "restic-v1"
    assert first["location"] == f"restic-v1:{LOCAL}:{SNAPSHOT}"
    assert first["total_bytes"] == first["logical_bytes"] == 25
    assert first["data_added_bytes"] == 10 and first["stored_bytes"] == 5
    assert second["data_added_bytes"] == second["stored_bytes"] == 0
    assert second["parent_snapshot_id"] == SNAPSHOT
    backups = [command for command in process.commands if "backup" in command]
    assert backups[0][-1] == backups[1][-1] == str(payload["snapshot_dir"])
    assert "--force" in backups[0]
    assert backups[1][backups[1].index("--parent") + 1] == SNAPSHOT
    assert second["verification"]["verified"] is True
    assert second["verification"]["payload_read_verified"] is False
    assert len([command for command in process.commands if "check" in command]) == 2


def test_save_rejects_unvalidated_tree_or_parent_from_another_source(setup):
    adapter, _, payload = _adapter(setup)
    with pytest.raises(engine.ResticError, match="capture validation"):
        adapter.save_payload("fixture", {**payload, "verification": {"verified": False}})
    with pytest.raises(engine.ResticError, match="Explicit parent"):
        adapter.save_payload("fixture", payload, parent_snapshot="9" * 64)


def test_failed_local_check_does_not_claim_verified_success(setup):
    adapter, process, payload = _adapter(setup)
    process.fail_check = True
    with pytest.raises(engine.ResticError, match="verification failed"):
        adapter.save_payload("fixture", payload)
    assert process.local_snapshots  # Native snapshot still exists for investigation.


def test_native_lock_failure_is_reported_without_claiming_integrity_failure(setup):
    adapter, process, payload = _adapter(setup)
    process.check_failure = 11
    with pytest.raises(engine.ResticError, match=r"failed to lock repository \(exit 11\)"):
        adapter.save_payload("fixture", payload)
    assert process.local_snapshots  # Shared backup lock succeeds; exclusive check fails.
    failed = adapter.check(monthly_state={})
    assert failed["verified"] is False
    assert failed["state"].get("next_bucket", 1) == 1
    assert "failed to lock repository" in failed["error"]
    assert "untrusted credential-like diagnostics" not in failed["error"]
    assert not any("unlock" in command or "--no-lock" in command for command in process.commands)


def test_copy_requires_durable_checkpoint_and_native_copy_only(setup):
    adapter, process, _ = _adapter(setup)
    with pytest.raises(engine.ResticError, match="durable"):
        adapter.sync(SNAPSHOT)
    saves, persist = _persisted()
    result = adapter.sync(SNAPSHOT, persist=persist)
    assert result["status"] == "verified"
    assert saves[0]["pending_snapshot_ids"] == [SNAPSHOT]
    assert result["remote_snapshot_id"] != SNAPSHOT
    command = next(command for command in process.commands if "copy" in command)
    assert command[0] == "restic" and "--from-repo" in command
    assert not any(command[1] in {"sync", "copy", "purge", "delete"} for command in process.commands if command[0] == "rclone")
    metadata = [command for command in process.commands if command[:2] == ["rclone", "lsjson"] and "--stat" in command]
    assert len(metadata) == 2 and all("--hash-type" in command and "SHA-256" in command for command in metadata)
    assert result["verification"]["offsite"]["new_object_bytes"] == sum(map(len, process.objects.values()))


def test_checkpoint_failure_prevents_any_remote_copy(setup):
    adapter, process, _ = _adapter(setup)

    def unavailable(_):
        raise OSError("fixture journal unavailable")

    with pytest.raises(OSError, match="journal unavailable"):
        adapter.sync(SNAPSHOT, persist=unavailable)
    assert not any("copy" in command for command in process.commands)


def test_copy_interruption_reconstructs_scope_even_when_retry_copies_zero_objects(setup):
    adapter, process, _ = _adapter(setup)
    saves, persist = _persisted()
    process.copy_failure = 1
    failed = adapter.sync(SNAPSHOT, persist=persist)
    assert failed["status"] == "pending"
    assert failed["state"]["verified_objects"] == {}
    assert failed["state"]["pending_snapshot_ids"] == [SNAPSHOT]
    process.copy_failure = None
    retried = adapter.sync(SNAPSHOT, state=saves[-1], persist=persist)
    assert retried["status"] == "verified"
    assert retried["verification"]["offsite"]["new_object_bytes"] == 0
    assert len(retried["state"]["verified_objects"]) == 2
    assert retried["state"]["pending_objects"] == []


def test_hash_mismatch_fails_closed_and_dedup_copy_does_not_clear_it(setup):
    adapter, process, _ = _adapter(setup)
    bad_path = process.add_object(b"encrypted-pack")
    process.bad_hashes.add(bad_path)
    saves, persist = _persisted()
    first = adapter.sync(SNAPSHOT, persist=persist)
    assert first["status"] == "failed"
    assert bad_path in first["state"]["mismatches"]
    second = adapter.sync(SNAPSHOT, state=saves[-1], persist=persist)
    assert second["status"] == "failed"
    assert second["state"]["mismatches"] == first["state"]["mismatches"]
    assert second["verification"]["verified"] is False
    assert not any(command[:2] == ["rclone", "cat"] for command in process.commands)
    process.bad_hashes.clear()
    assert adapter.sync(SNAPSHOT, state=saves[-1], persist=persist)["status"] == "verified"


def test_missing_sha_downloads_only_affected_unknown_object(setup):
    adapter, process, _ = _adapter(setup)
    affected = process.add_object(b"encrypted-pack")
    process.missing_hashes.add(affected)
    _saves, persist = _persisted()
    result = adapter.sync(SNAPSHOT, persist=persist)
    assert result["status"] == "verified"
    downloads = [command for command in process.commands if command[:2] == ["rclone", "cat"]]
    assert len(downloads) == 1 and downloads[0][2].endswith(affected)
    assert result["state"]["verified_objects"][affected]["method"] == "affected-object-download-sha256"


def test_fresh_provider_storage_identity_is_required(setup):
    adapter, process, _ = _adapter(setup)
    affected = process.add_object(b"encrypted-pack")
    process.changed_identity.add(affected)
    _, persist = _persisted()
    result = adapter.sync(SNAPSHOT, persist=persist)
    assert result["status"] == "failed"
    assert "identity" in result["state"]["mismatches"][affected]


def test_remote_outage_preserves_local_snapshot_and_pending_state(setup):
    adapter, process, payload = _adapter(setup)
    saved = adapter.save_payload("fixture", payload)
    process.remote_unavailable = True
    _, persist = _persisted()
    result = adapter.sync(saved["snapshot_id"], persist=persist)
    assert result["status"] == "pending"
    assert result["state"]["pending_snapshot_ids"] == [SNAPSHOT]
    assert process.local_snapshots[0]["id"] == SNAPSHOT
    assert "untrusted credential" not in json.dumps(result)


def test_cancelled_copy_keeps_retryable_journal_and_caller_cancellation(setup):
    adapter, process, _ = _adapter(setup)
    saves, persist = _persisted()
    process.cancel_copy = True
    with pytest.raises(engine.BackupCancelled):
        adapter.sync(SNAPSHOT, persist=persist)
    assert saves[-1]["status"] == "pending" and saves[-1]["pending_snapshot_ids"] == [SNAPSHOT]
    process.cancel_copy = False
    assert adapter.sync(SNAPSHOT, state=saves[-1], persist=persist)["status"] == "verified"


def test_wallclock_retention_pins_pending_minimum_three_and_last_good():
    now = datetime(2026, 9, 29, tzinfo=UTC)
    snapshots: list[RetentionSnapshot] = [{"id": f"{number:064x}", "tags": ["source:fixture"], "time": (now - timedelta(days=age)).isoformat()} for number, age in enumerate([0, 7, 14, 15, 20, 30, 90], 1)]
    selected = engine.select_retention(snapshots, {"fixture": 14}, now=now, pinned=[snapshots[3]["id"]], pending=[snapshots[4]["id"]], last_good={"fixture": snapshots[5]["id"]})
    assert selected["delete"] == [snapshots[6]["id"]]
    assert selected["reasons"][snapshots[2]["id"]] == ["minimum-three", "within-window"]
    assert selected["reasons"][snapshots[3]["id"]] == ["pinned"]
    assert selected["reasons"][snapshots[4]["id"]] == ["pending-offsite"]
    assert selected["reasons"][snapshots[5]["id"]] == ["last-good"]
    # Three ancient points survive even when no point is inside its window.
    assert engine.select_retention(snapshots[-3:], {"fixture": 7}, now=now)["delete"] == []


def test_retention_protects_unmanaged_and_invalid_timestamps():
    snapshots = [{"id": "a" * 64, "time": "bad", "tags": ["source:fixture"]}, {"id": "b" * 64, "time": "2000-01-01T00:00:00Z"}]
    assert engine.select_retention(snapshots, {"fixture": 7})["delete"] == []


def test_retention_preview_and_offsite_qualification_guard(setup):
    adapter, process, _ = _adapter(setup)
    now = datetime.now(UTC)
    process.local_snapshots = [{"id": f"{number:064x}", "tags": ["source:fixture"], "time": (now - timedelta(days=number + 40)).isoformat()} for number in range(1, 6)]
    result = adapter.retention({"fixture": 14})
    command = next(command for command in process.commands if "forget" in command)
    assert result["status"] == "preview" and "--dry-run" in command and "--prune" not in command
    with pytest.raises(engine.ResticError, match="qualified"):
        adapter.retention({"fixture": 14}, remote=True, dry_run=False)


def test_repository_lock_is_exclusive_and_released_on_failure(setup):
    config, _, _ = setup
    with pytest.raises(RuntimeError, match="fixture failure"), engine.repository_lock(config):
        lockfile = config.lock_directory / (hashlib.sha256(str(config.local_repository.resolve()).encode()).hexdigest() + ".lock")
        descriptor = os.open(lockfile, os.O_RDWR)
        try:
            with pytest.raises(BlockingIOError):
                engine.fcntl.flock(descriptor, engine.fcntl.LOCK_EX | engine.fcntl.LOCK_NB)
        finally:
            os.close(descriptor)
        raise RuntimeError("fixture failure")
    with engine.repository_lock(config):
        pass


def test_waiting_repository_lock_checks_cancellation(setup, monkeypatch):
    config, _, _ = setup
    attempts = []

    def cancelled():
        attempts.append(True)
        raise engine.BackupCancelled("fixture cancellation")

    monkeypatch.setattr(engine, "check_backup_cancelled", cancelled)
    with pytest.raises(engine.BackupCancelled), engine.repository_lock(config):
        pytest.fail("lock acquired despite cancellation")
    assert attempts


def test_restore_returns_materialized_payload_root_and_literal_partial_include(setup, tmp_path):
    adapter, process, payload = _adapter(setup)
    saved = adapter.save_payload("fixture", payload)
    destination = tmp_path / "isolated"
    destination.mkdir(mode=0o700)
    result = adapter.restore(saved["snapshot_id"], destination, include=[".summitflow-recovery/repository.bundle"])
    assert Path(result["payload_root"]) == destination / payload["snapshot_dir"].relative_to("/")
    assert result["verification"] == {"verified": True, "method": "restic-restore-verify", "partial": True}
    command = next(command for command in process.commands if "restore" in command)
    assert "--verify" in command
    assert command[command.index("--include") + 1] == str(payload["snapshot_dir"] / ".summitflow-recovery/repository.bundle")
    with pytest.raises(engine.ResticError, match="empty private"):
        adapter.restore(saved["snapshot_id"], destination)


def test_remote_restores_use_unique_empty_private_job_caches_then_remove_them(setup, tmp_path, monkeypatch):
    adapter, process, payload = _adapter(setup)
    saved = adapter.save_payload("fixture", payload)
    remote_snapshot = "4" * 64
    process.remote_snapshots = [{**process.local_snapshots[0], "id": remote_snapshot}]
    job = tmp_path / "restore-job"
    job.mkdir(mode=0o700)
    existing = job / "existing-cache"
    existing.mkdir(mode=0o700)
    (existing / "old-data").write_text("synthetic stale cache")
    monkeypatch.setenv("RESTIC_CACHE_DIR", str(existing))
    caches = []

    def observe(command, **kwargs):
        if "restore" in command:
            assert "--cache-dir" in command
            assert "--no-cache" not in command
            assert "--verify" in command and "--no-lock" not in command
            assert command[command.index("--repo") + 1] == "rclone:fixture:repository"
            assert command[command.index("restore") + 1] == remote_snapshot
            assert "RESTIC_CACHE_DIR" not in kwargs["env"]
            cache = Path(command[command.index("--cache-dir") + 1])
            assert cache.is_relative_to(tmp_path / "scratch")
            assert not cache.is_relative_to(job)
            assert cache.is_dir() and not cache.is_symlink() and cache.stat().st_mode & 0o777 == 0o700
            assert list(cache.iterdir()) == []
            caches.append(cache)
            (cache / "downloaded-this-operation").write_text("synthetic remote metadata")
        return process(command, **kwargs)

    adapter._runner = observe
    for number in range(2):
        destination = job / f"destination-{number}"
        destination.mkdir(mode=0o700)
        assert adapter.restore(remote_snapshot, destination, remote=True)["verification"]["verified"] is True
        assert not caches[-1].exists()
    assert len(set(caches)) == 2
    assert (existing / "old-data").read_text() == "synthetic stale cache"
    assert saved["snapshot_id"] == SNAPSHOT


@pytest.mark.parametrize("failure", ["native-failure", "cancellation", "invalid-materialization"])
def test_restore_job_cache_is_removed_on_failure(setup, tmp_path, failure):
    adapter, process, payload = _adapter(setup)
    saved = adapter.save_payload("fixture", payload)
    job = tmp_path / "restore-job"
    job.mkdir(mode=0o700)
    destination = job / "destination"
    destination.mkdir(mode=0o700)
    caches = []

    def fail(command, **kwargs):
        if "restore" in command:
            assert "--cache-dir" in command
            cache = Path(command[command.index("--cache-dir") + 1])
            caches.append(cache)
            (cache / "temporary-metadata").write_text("synthetic remote metadata")
            if failure == "cancellation":
                raise engine.BackupCancelled("synthetic cancellation")
            return subprocess.CompletedProcess(command, 1 if failure == "native-failure" else 0, "{}", "PRIVATE_DIAGNOSTIC")
        return process(command, **kwargs)

    adapter._runner = fail
    expected = engine.BackupCancelled if failure == "cancellation" else engine.ResticError
    with pytest.raises(expected):
        adapter.restore(saved["snapshot_id"], destination)
    assert len(caches) == 1
    assert not caches[0].exists()


@pytest.mark.parametrize("include", ["../outside", "/outside", "*", "file[1]"])
def test_restore_rejects_nonliteral_or_escaping_include(setup, tmp_path, include):
    adapter, _, payload = _adapter(setup)
    saved = adapter.save_payload("fixture", payload)
    destination = tmp_path / "isolated"
    destination.mkdir(mode=0o700)
    with pytest.raises(engine.ResticError, match="literal path"):
        adapter.restore(saved["snapshot_id"], destination, include=[include])


def test_monthly_deterministic_bucket_advances_only_on_success_and_reports_stale(setup):
    adapter, process, _ = _adapter(setup)
    result = adapter.check(remote=True, monthly_state={})
    assert result["bucket"] == 1 and result["state"]["next_bucket"] == 2
    assert result["stale_buckets"] == list(range(2, 31))
    assert "--read-data-subset=1/30" in process.commands[-1]
    process.fail_check = True
    failed = adapter.check(remote=True, monthly_state=result["state"])
    assert failed["status"] == "failed" and failed["state"]["next_bucket"] == 2
    assert failed["state"]["successful_runs"] == 1
    process.fail_check = False
    state = result["state"]
    for _ in range(29):
        success = adapter.check(remote=True, monthly_state=state)
        state = success["state"]
    assert success["coverage_complete"] is True
    assert state["next_bucket"] == 1 and state["successful_runs"] == 30
    state["bucket_success_at"]["2"] = (datetime.now(UTC) - timedelta(days=31)).isoformat()
    assert 2 in adapter.check(remote=True, monthly_state=state)["stale_buckets"]


def test_weekly_prune_is_independent_qualified_headroom_bounded_and_preview_first(setup):
    config, process, _ = setup
    adapter = engine.ResticAdapter(replace(config, offsite_prune_qualified=True), runner=process)
    assert adapter.prune(remote=True, available_bytes=1024**4, state={"pending_snapshot_ids": [SNAPSHOT]})["reason"] == "pending-verification"
    assert adapter.prune(remote=True, available_bytes=1)["reason"] == "insufficient-headroom"
    assert adapter.prune(remote=True, available_bytes=1024**4, last_prune_at=datetime.now(UTC).isoformat())["reason"] == "weekly-cadence"
    _, persist = _persisted()
    result = adapter.prune(remote=True, available_bytes=1024**4, dry_run=False, state={"status": "verified"}, persist=persist)
    assert result["status"] == "completed" and result["max_unused"] == "5%"
    assert result["physical_bytes_confirmed"] is True
    assert result["physical_bytes_after"] == sum(len(value) for value in process.objects.values())
    assert result["free_bytes"] == 500000
    commands = [command for command in process.commands if "prune" in command]
    assert len(commands) == 2 and "--dry-run" in commands[0] and "--dry-run" not in commands[1]
    assert all("rclone.args=serve restic --stdio --drive-use-trash=false" in command for command in commands)
    process.fail_check = True
    failed = adapter.prune(remote=True, available_bytes=1024**4)
    assert failed["status"] == "failed" and failed["backup_verification_unchanged"] is True
    assert not any("purge" in command or "cleanup" in command for command in process.commands)


def test_prune_uses_one_fresh_operation_cache_and_bounds_planning(setup):
    config, process, _ = setup
    seen: list[tuple[list[str], dict[str, Any]]] = []

    def observe(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if "prune" in command:
            cache = Path(command[command.index("--cache-dir") + 1])
            assert cache.is_dir() and not cache.is_symlink() and not any(cache.iterdir())
            assert "--no-cache" not in command
            seen.append((command, kwargs))
        return process(command, **kwargs)

    adapter = engine.ResticAdapter(replace(config, offsite_prune_qualified=True), runner=observe)
    _, persist = _persisted()
    assert adapter.prune(remote=True, available_bytes=1024**4, dry_run=False, state={"status": "verified"}, persist=persist)["status"] == "completed"
    (plan, plan_kwargs), (apply, apply_kwargs) = seen
    assert "--dry-run" in plan and plan_kwargs["timeout"] == engine.PRUNE_PLAN_TIMEOUT_SECONDS
    assert "timeout" not in apply_kwargs  # Mutation is never interrupted by the bound.
    assert plan[plan.index("--cache-dir") + 1] == apply[apply.index("--cache-dir") + 1]
    assert not Path(plan[plan.index("--cache-dir") + 1]).exists()


def test_prune_planning_timeout_fails_without_mutation(setup):
    config, process, _ = setup
    applied: list[list[str]] = []

    def slow(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if "prune" in command:
            if "--dry-run" in command:
                raise subprocess.TimeoutExpired(command, kwargs["timeout"])
            applied.append(command)
        return process(command, **kwargs)

    adapter = engine.ResticAdapter(replace(config, offsite_prune_qualified=True), runner=slow)
    _, persist = _persisted()
    result = adapter.prune(remote=True, available_bytes=1024**4, dry_run=False, state={"status": "verified"}, persist=persist)
    assert result["status"] == "failed" and "planning exceeded" in result["error"]
    assert result["backup_verification_unchanged"] is True
    assert applied == []
    assert (result["state"].get("maintenance") or {}).get("status") != "pending"


def test_offsite_prune_defaults_to_disabled(setup):
    adapter, process, _ = _adapter(setup)
    assert adapter.prune(remote=True, available_bytes=1024**4)["reason"] == "offsite-not-qualified"
    assert process.commands == []


def test_known_unchanged_objects_do_not_spawn_per_object_hash_processes(setup):
    adapter, process, _ = _adapter(setup)
    _, persist = _persisted()
    first = adapter.sync(SNAPSHOT, persist=persist)
    count = len([command for command in process.commands if "--stat" in command])
    assert count == 2
    second = adapter.sync(SNAPSHOT, state=first["state"], persist=persist)
    assert second["status"] == "verified"
    assert len([command for command in process.commands if "--stat" in command]) == count
    assert all(value.get("last_seen_at") for value in second["state"]["verified_objects"].values())


def test_missing_provider_hash_and_corrupted_download_fails_closed(setup):
    adapter, process, _ = _adapter(setup)
    _, persist = _persisted()
    affected = process.add_object(b"encrypted index", "index")
    process.objects[affected] = b"tampered bytes"
    process.missing_hashes.add(affected)
    result = adapter.sync(SNAPSHOT, persist=persist)
    assert result["status"] == "failed"
    assert affected in result["state"]["mismatches"]


def test_public_repository_identity_is_authenticated_and_locked(setup):
    adapter, _, _ = _adapter(setup)
    assert adapter.repository_identity() == {"id": LOCAL, "version": 2, "chunker_polynomial": "fixture"}
    assert adapter.repository_identity(remote=True)["id"] == REMOTE


def test_quota_uses_public_provider_about_operation(setup):
    adapter, process, _ = _adapter(setup)
    assert adapter.quota_free_bytes() == 500000
    assert process.commands[-1][:3] == ["rclone", "about", "fixture:repository"]


def test_failed_copy_is_reconciled_when_a_new_snapshot_is_requested(setup):
    adapter, process, _ = _adapter(setup)
    _, persist = _persisted()
    process.remote_unavailable = True
    failed = adapter.sync(SNAPSHOT, persist=persist)
    process.remote_unavailable = False
    second_id = "4" * 64
    success = adapter.sync(second_id, state=failed["state"], persist=persist)
    assert success["status"] == "verified"
    command = next(command for command in process.commands if "copy" in command)
    assert command[-2:] == [SNAPSHOT, second_id]
    assert set(success["state"]["remote_snapshots"]) == {SNAPSHOT, second_id}


def test_recorded_object_disappearance_is_not_silently_retired(setup):
    adapter, process, _ = _adapter(setup)
    _, persist = _persisted()
    extra = process.add_object(b"previous encrypted index", "index")
    first = adapter.sync(SNAPSHOT, persist=persist)
    del process.objects[extra]
    second = adapter.sync(SNAPSHOT, state=first["state"], persist=persist)
    assert second["status"] == "failed" and extra in second["state"]["mismatches"]


def test_qualified_prune_retires_removed_objects_only_after_verifying_repacked_objects(setup):
    config, process, _ = setup
    adapter = engine.ResticAdapter(replace(config, offsite_prune_qualified=True), runner=process)
    _, persist = _persisted()
    old = process.add_object(b"old encrypted index", "index")
    verified = adapter.sync(SNAPSHOT, persist=persist)["state"]

    def prune_runner(command, **kwargs):
        if "prune" in command and "--dry-run" not in command:
            del process.objects[old]
            process.add_object(b"new repacked ciphertext")
        return process(command, **kwargs)

    adapter._runner = prune_runner
    result = adapter.prune(remote=True, state=verified, persist=persist, available_bytes=1024**4, dry_run=False)
    assert result["status"] == "completed"
    assert old not in result["state"]["verified_objects"]
    assert result["state"]["pending_objects"] == []
    new_path = next(path for path in process.objects if process.objects[path] == b"new repacked ciphertext")
    assert result["state"]["verified_objects"][new_path]["method"] == "provider-sha256"
    assert result["state"]["maintenance"]["status"] == "completed"
    assert result["physical_bytes_confirmed"] is True
    assert result["physical_bytes_after"] == sum(len(value) for value in process.objects.values())
    assert result["reclaimed_bytes"] == max(0, result["physical_bytes_before"] - result["physical_bytes_after"])
    retry = adapter.sync(SNAPSHOT, state=result["state"], persist=persist)
    assert retry["status"] == "verified"


def _retention_fixture(setup):
    config, process, _ = setup
    adapter = engine.ResticAdapter(replace(config, offsite_prune_qualified=True), runner=process)
    now = datetime.now(UTC)
    mapping = {}
    for number in range(1, 6):
        path = process.add_object(f"remote snapshot {number}".encode(), "snapshots")
        snapshot_id = Path(path).name
        process.remote_snapshots.append({"id": snapshot_id, "tags": ["source:fixture"], "time": (now - timedelta(days=number + 40)).isoformat(), "paths": [str(process.payload)]})
        mapping[f"{number:064x}"] = snapshot_id
    process.add_object(b"unrelated immutable key", "keys")
    process.add_object(b"unrelated immutable pack")
    journal = {"version": 1, "local_repository_id": LOCAL, "remote_repository_id": REMOTE, "status": "verified", "verified_objects": {path: {"id": "storage:" + path, "size": len(content), "mod_time": None} for path, content in process.objects.items()}, "pending_objects": [], "pending_snapshot_ids": [], "mismatches": {}, "remote_snapshots": mapping}
    return adapter, process, journal


def _forget(process, command):
    if "forget" in command and "--dry-run" not in command:
        targets = set(command[command.index("forget") + 1:])
        process.remote_snapshots = [item for item in process.remote_snapshots if item["id"] not in targets]
        for snapshot_id in targets:
            process.objects.pop("snapshots/" + snapshot_id, None)


@pytest.mark.parametrize("crash_phase", ["command_completed", "completed"])
def test_forget_resume_reconciles_saved_ids_after_empty_selection_and_persist_crash(setup, crash_phase):
    adapter, process, journal = _retention_fixture(setup)
    durable = []

    def persist(state):
        intent = state.get("maintenance") or {}
        if (crash_phase == "completed" and intent.get("status") == "completed") or (crash_phase == "command_completed" and intent.get("phase") == "command_completed"):
            raise OSError("fixture crash after native forget")
        durable.append(state)

    def forget_runner(command, **kwargs):
        _forget(process, command)
        return process(command, **kwargs)

    adapter._runner = forget_runner
    with pytest.raises(OSError, match="crash after native forget"):
        adapter.retention({"fixture": 14}, remote=True, state=journal, persist=persist, dry_run=False)
    saved = durable[-1]
    authorized = saved["maintenance"]["snapshot_ids"]
    assert len(authorized) == 2
    assert all("snapshots/" + snapshot_id not in process.objects for snapshot_id in authorized)
    assert engine.select_retention(process.remote_snapshots, {"fixture": 14})["delete"] == []
    calls = len([command for command in process.commands if "forget" in command])
    resumed = adapter.retention({"fixture": 14}, remote=True, state=saved, persist=durable.append, dry_run=False)
    assert resumed["status"] == "completed" and resumed["delete"] == authorized
    assert resumed["state"]["maintenance"]["status"] == "completed"
    assert resumed["state"]["maintenance"]["started_at"] == saved["maintenance"]["started_at"]
    assert len([command for command in process.commands if "forget" in command]) == calls
    assert set(resumed["state"]["remote_snapshots"].values()) == set(journal["remote_snapshots"].values()) - set(authorized)
    assert not any("snapshots/" + snapshot_id in resumed["state"]["verified_objects"] for snapshot_id in authorized)


@pytest.mark.parametrize("kind", ["keys", "data"])
def test_forget_refuses_unexpected_key_or_pack_removal_and_keeps_original_scope(setup, kind):
    adapter, process, journal = _retention_fixture(setup)
    durable, persist = _persisted()
    unexpected = next(path for path in process.objects if path.startswith(kind + "/"))

    def destructive_runner(command, **kwargs):
        _forget(process, command)
        if "forget" in command and "--dry-run" not in command:
            del process.objects[unexpected]
        return process(command, **kwargs)

    adapter._runner = destructive_runner
    with pytest.raises(engine.ResticError, match="unauthorized"):
        adapter.retention({"fixture": 14}, remote=True, state=journal, persist=persist, dry_run=False)
    failed = durable[-1]
    assert failed["maintenance"]["status"] == "pending"
    assert unexpected in failed["verified_objects"] and unexpected in failed["mismatches"]
    assert failed["remote_snapshots"] == journal["remote_snapshots"]
    with pytest.raises(engine.ResticError, match="unauthorized"):
        adapter.retention({"fixture": 14}, remote=True, state=failed, persist=persist, dry_run=False)
    assert durable[-1]["maintenance"]["snapshot_ids"] == failed["maintenance"]["snapshot_ids"]


def test_prune_new_pack_corruption_fails_before_completed_and_cannot_be_erased_by_retry(setup):
    adapter, process, journal = _retention_fixture(setup)
    durable, persist = _persisted()
    new_path = None

    def corrupting_runner(command, **kwargs):
        nonlocal new_path
        if "prune" in command and "--dry-run" not in command:
            new_path = process.add_object(b"new repacked ciphertext")
            process.bad_hashes.add(new_path)
        return process(command, **kwargs)

    adapter._runner = corrupting_runner
    result = adapter.prune(remote=True, state=journal, persist=persist, available_bytes=1024**4, dry_run=False)
    assert result["status"] == "failed"
    assert result["state"]["maintenance"]["status"] == "pending"
    assert new_path in result["state"]["pending_objects"] and new_path in result["state"]["mismatches"]
    assert new_path not in result["state"]["verified_objects"]
    assert not any(state.get("maintenance", {}).get("status") == "completed" for state in durable)
    count = len([command for command in process.commands if "prune" in command])
    retry = adapter.prune(remote=True, state=durable[-1], persist=persist, available_bytes=1024**4, dry_run=False)
    assert retry["status"] == "failed"
    assert len([command for command in process.commands if "prune" in command]) == count
    process.bad_hashes.clear()
    success = adapter.prune(remote=True, state=durable[-1], persist=persist, dry_run=False)
    assert success["status"] == "completed" and success["resumed"] is True
    assert success["state"]["pending_objects"] == []


@pytest.mark.parametrize("kind", ["keys", "snapshots"])
def test_prune_cannot_retire_key_or_snapshot_objects(setup, kind):
    adapter, process, journal = _retention_fixture(setup)
    _, persist = _persisted()
    unexpected = next(path for path in process.objects if path.startswith(kind + "/"))

    def corrupting_runner(command, **kwargs):
        if "prune" in command and "--dry-run" not in command:
            del process.objects[unexpected]
        return process(command, **kwargs)

    adapter._runner = corrupting_runner
    result = adapter.prune(remote=True, state=journal, persist=persist, available_bytes=1024**4, dry_run=False)
    assert result["status"] == "failed" and unexpected in result["state"]["mismatches"]
    assert unexpected in result["state"]["verified_objects"]
    assert result["state"]["remote_snapshots"] == journal["remote_snapshots"]


def test_resume_does_not_overwrite_a_different_operation_intent(setup):
    adapter, process, journal = _retention_fixture(setup)
    _, persist = _persisted()
    journal["maintenance"] = {"version": 1, "status": "pending", "operation": "prune", "baseline_objects": sorted(process.objects), "snapshot_ids": [], "started_at": "2026-09-01T00:00:00Z"}
    with pytest.raises(engine.ResticError, match="different interrupted"):
        adapter.retention({"fixture": 14}, remote=True, state=journal, persist=persist, dry_run=False)
    assert journal["maintenance"]["operation"] == "prune"
    assert not any("forget" in command for command in process.commands)


def test_prune_resume_after_completion_write_crash_verifies_existing_new_pack_without_rerun(setup):
    adapter, process, journal = _retention_fixture(setup)
    durable = []
    new_path = None

    def persist(state):
        if state.get("maintenance", {}).get("status") == "completed":
            raise OSError("fixture final prune checkpoint crash")
        durable.append(state)

    def prune_runner(command, **kwargs):
        nonlocal new_path
        if "prune" in command and "--dry-run" not in command:
            new_path = process.add_object(b"new valid repack")
        return process(command, **kwargs)

    adapter._runner = prune_runner
    with pytest.raises(OSError, match="checkpoint crash"):
        adapter.prune(remote=True, state=journal, persist=persist, available_bytes=1024**4, dry_run=False)
    saved = durable[-1]
    assert saved["maintenance"]["phase"] == "command_completed"
    commands = len([command for command in process.commands if "prune" in command])
    resumed = adapter.prune(remote=True, state=saved, persist=durable.append, dry_run=False)
    assert resumed["status"] == "completed" and resumed["resumed"] is True
    assert resumed["state"]["verified_objects"][new_path]["method"] == "provider-sha256"
    assert resumed["state"]["pending_objects"] == []
    assert len([command for command in process.commands if "prune" in command]) == commands


def test_prune_prepared_intent_crash_reconciles_before_running_a_saved_new_intent(setup):
    adapter, process, journal = _retention_fixture(setup)
    durable = []

    def stopping_runner(command, **kwargs):
        if "prune" in command and "--dry-run" not in command:
            raise OSError("fixture crash before native mutation")
        return process(command, **kwargs)

    adapter._runner = stopping_runner
    with pytest.raises(OSError, match="before native mutation"):
        adapter.prune(remote=True, state=journal, persist=durable.append, available_bytes=1024**4, dry_run=False)
    saved = durable[-1]
    assert saved["maintenance"]["phase"] == "prepared"
    adapter._runner = process
    resumed = adapter.prune(remote=True, state=saved, persist=durable.append, available_bytes=1024**4, dry_run=False)
    assert resumed["status"] == "completed"
    assert resumed["state"]["maintenance"]["phase"] == "command_completed"
    assert any("prune" in command and "--dry-run" not in command for command in process.commands)


def test_interrupted_maintenance_and_wrong_repository_journal_fail_closed(setup):
    adapter, process, _ = _adapter(setup)
    _, persist = _persisted()
    result = adapter.sync(SNAPSHOT, state={"maintenance": {"status": "pending"}}, persist=persist)
    assert result["status"] == "pending"
    assert not any("copy" in command for command in process.commands)
    with pytest.raises(engine.ResticError, match="different local"):
        adapter.sync(SNAPSHOT, state={"local_repository_id": "f" * 64}, persist=persist)
