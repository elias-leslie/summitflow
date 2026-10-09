"""Exercise disposable backup writers and process paths with synthetic mount evidence."""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.tasks import (
    backup_activity,
    backup_native,
    backup_native_archive,
    backup_native_infra,
    backup_restore_test,
)
from app.tasks import backup_native_recovery as recovery
from app.utils import transient_scratch as scratch
from tests.tasks.test_backup_native_recovery import _git


def test_bulk_process_routes_parent_files_child_temp_and_filtered_environment(backup_job_scratch, monkeypatch):
    monkeypatch.setenv("RESTIC_PASSWORD", "inherited-fixture-must-not-reappear")
    monkeypatch.setenv("TMPDIR", "/inherited/root-temp")
    parents = []
    temporary_file = backup_activity.tempfile.TemporaryFile

    def record(*args, **kwargs):
        parents.append(Path(kwargs["dir"]))
        return temporary_file(*args, **kwargs)

    monkeypatch.setattr(backup_activity.tempfile, "TemporaryFile", record)
    code = "import os,tempfile; p=tempfile.mkstemp()[1]; print(p); print(os.getenv('RESTIC_PASSWORD','absent')); print(os.environ['XDG_CACHE_HOME'])"
    result = backup_activity.run_bulk_process([sys.executable, "-c", code], env={"PATH": os.environ["PATH"]})
    temporary, password, cache = result.stdout.splitlines()
    assert password == "absent"
    assert parents[0] == parents[1]
    assert parents[0].parent == backup_job_scratch / f"st-backups-{os.getuid()}"
    assert Path(temporary).parent == parents[0] / "tmp"
    assert Path(cache) == parents[0] / "cache"
    assert not parents[0].exists()


def test_bulk_process_missing_mount_refuses_before_launch(backup_job_scratch, monkeypatch):
    monkeypatch.setattr(Path, "is_mount", lambda _path: False)
    launch = Mock(side_effect=AssertionError("must not launch"))
    monkeypatch.setattr(backup_activity.subprocess, "Popen", launch)
    with pytest.raises(scratch.ScratchError, match="unavailable or unsafe"):
        backup_activity.run_bulk_process([sys.executable, "-c", "pass"])
    launch.assert_not_called()


def test_bulk_process_observed_reserve_crossing_reaps_and_cleans(backup_job_scratch, monkeypatch):
    usage = shutil.disk_usage(backup_job_scratch)
    reserve = 25 * 1024**3
    monkeypatch.setenv("SF_HOST_RETENTION_PRESSURE_MIN_FREE_GB", "25")
    monkeypatch.setattr(backup_activity, "CONTROL_POLL_SECONDS", 0.01)
    monkeypatch.setattr(scratch.shutil, "disk_usage", lambda _path: usage._replace(
        free=reserve - 1 if list(backup_job_scratch.rglob("capacity-marker")) else reserve + 1024**3,
    ))
    processes = []
    popen = subprocess.Popen

    def record(*args, **kwargs):
        process = popen(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(backup_activity.subprocess, "Popen", record)
    code = "import os,time; from pathlib import Path; (Path(os.environ['TMPDIR'])/'capacity-marker').touch(); time.sleep(60)"
    with pytest.raises(scratch.ScratchError, match="Insufficient"):
        backup_activity.run_bulk_process([sys.executable, "-c", code])
    assert len(processes) == 1 and processes[0].poll() is not None
    assert not list(backup_job_scratch.glob("st-backups-*/*"))


def test_nested_jobs_restore_process_binding_and_cleanup(backup_job_scratch, monkeypatch):
    monkeypatch.setenv("RCLONE_CONFIG", "inherited-fixture")
    with scratch.disposable_scratch("outer-") as outer:
        outer_environment = scratch.scratch_subprocess_env({"PATH": "/fixture"})
        assert "RCLONE_CONFIG" not in outer_environment
        with pytest.raises(InterruptedError), scratch.disposable_scratch("inner-") as inner:
            assert scratch.scratch_subprocess_env()["TMPDIR"] == str(inner / "tmp")
            raise InterruptedError("fixture cancellation")
        assert not inner.exists()
        assert scratch.scratch_subprocess_env()["TMPDIR"] == str(outer / "tmp")
    assert not outer.exists()


@pytest.mark.parametrize("kind", ["plain", "gzip"])
def test_streaming_database_writers_check_next_actual_bytes(backup_job_scratch, monkeypatch, kind):
    written = []
    usage = shutil.disk_usage(backup_job_scratch)
    reserve = 25 * 1024**3
    monkeypatch.setenv("SF_HOST_RETENTION_PRESSURE_MIN_FREE_GB", "25")

    def usage_for(path):
        written.append(path)
        return usage._replace(free=reserve)

    def bulk(_command, **kwargs):
        kwargs["stdout_sink"](io.BytesIO(b"unbounded SQL fixture"))
        return subprocess.CompletedProcess([], 0, b"", b"")

    monkeypatch.setattr(scratch.shutil, "disk_usage", usage_for)
    monkeypatch.setattr(backup_native_archive, "run_bulk_process", bulk)
    destination = backup_job_scratch / "dump"
    stream = backup_native_archive._run_plain_stream if kind == "plain" else backup_native_archive._run_gzip_stream
    with pytest.raises(scratch.ScratchError, match="additional known bytes"):
        stream(["fixture"], destination, env={}, timeout=1)
    assert written and all(path == destination.parent for path in written)
    assert destination.stat().st_size == 0


@pytest.mark.parametrize("failure", [False, True])
@pytest.mark.parametrize("kind", ["project", "infrastructure"])
def test_native_archive_jobs_use_scratch_keep_durable_destination_and_cleanup(
    backup_job_scratch, tmp_path, monkeypatch, failure, kind,
):
    project = tmp_path / "project"
    project.mkdir()
    jobs = []

    def create(_project, name, staging, env, **_kwargs):
        jobs.append(staging)
        assert staging.parent == backup_job_scratch / f"st-backups-{os.getuid()}"
        assert env["TMPDIR"] == str(staging / "tmp")
        archive = staging / f"{name}-fixture.tar.gz"
        archive.write_bytes(b"fixture plaintext")
        if failure:
            raise backup_activity.BackupCancelled("fixture cancellation")
        return {"archive_name": archive.name, "archive_path": archive, "total_bytes": archive.stat().st_size,
                "verification": {"verified": True}}

    def encrypt(source, destination, _env):
        assert source.parent == destination.parent == jobs[0]
        destination.write_bytes(b"fixture ciphertext")
        return {"content_checksum": "sha256:plain", "checksum": "sha256:cipher",
                "encrypted_bytes": destination.stat().st_size}

    if kind == "project":
        monkeypatch.setattr(backup_native, "_create_project_archive", create)
        monkeypatch.setattr(backup_native, "canonical_backup_source_roots", lambda: {})
        monkeypatch.setattr(backup_native, "encrypt_completed_archive", encrypt)
        monkeypatch.setattr(backup_native, "update_backup_index", lambda *_args: None)
        monkeypatch.setattr(backup_native, "apply_local_retention", lambda *_args: None)
        def run():
            return backup_native.run_project_backup(project_dir=str(project), source_id="fixture", local_only=True)
    else:
        def build(source, staging, name, **_kwargs):
            result = create(source, "infrastructure", staging, scratch.scratch_subprocess_env())
            return result["archive_path"], 1, result

        def finish(source, _source_id, result, archive, *_args, **_kwargs):
            destination = source / "backups" / result["archive_name"]
            destination.parent.mkdir(exist_ok=True)
            shutil.copy2(archive, destination)
            return {**result, "location": str(destination)}

        monkeypatch.setattr(backup_native_infra, "get_repo_root", lambda: project)
        monkeypatch.setattr(backup_native_infra, "get_host_config_root", lambda: tmp_path)
        monkeypatch.setattr(backup_native_infra, "_storage_config", lambda *_args: object())
        monkeypatch.setattr(backup_native_infra, "_build_infra_archive", build)
        monkeypatch.setattr(backup_native_infra, "encrypt_completed_archive", encrypt)
        monkeypatch.setattr(backup_native_infra, "_finish_infra_backup", finish)
        run = backup_native_infra.run_infra_backup
    if failure:
        with pytest.raises(backup_activity.BackupCancelled):
            run()
    else:
        result = run()
        assert Path(result["location"]).is_relative_to(project / "backups")
        assert Path(result["location"]).read_bytes() == b"fixture ciphertext"
    assert jobs and not jobs[0].exists()


def test_git_split_index_bundle_and_reuse_jobs_have_no_system_temp_fallback(
    backup_job_scratch, tmp_path, monkeypatch,
):
    project = tmp_path / "git-project"
    project.mkdir()
    _git(project, "init", "-b", "main")
    _git(project, "config", "user.name", "Fixture")
    _git(project, "config", "user.email", "fixture@example.invalid")
    (project / "file").write_text("base")
    _git(project, "add", ".")
    _git(project, "commit", "-m", "base")
    _git(project, "update-index", "--split-index")
    jobs = []
    temporary_directory = scratch.tempfile.TemporaryDirectory

    def record(*args, **kwargs):
        result = temporary_directory(*args, **kwargs)
        jobs.append(Path(result.name))
        return result

    monkeypatch.setattr(scratch.tempfile, "TemporaryDirectory", record)
    monkeypatch.setenv("TMPDIR", "/inherited/root-temp")
    state = recovery.git_state(project)
    assert state is not None and state["shared_index_path"]
    bundle = tmp_path / "git.bundle"
    recovery._create_git_bundle(project, bundle, state, Path(state["index_path"]))
    previous = {**state, "bundle_checksum": recovery._sha256(bundle)}
    destination = tmp_path / "reused.bundle"
    assert recovery._reuse_git_bundle(project, destination, state, {"bundle_path": bundle, "git": previous})
    assert {path.name.rsplit("-", 1)[0] for path in jobs} >= {
        "backup-git-shared-index", "backup-git-bundle", "backup-git-index", "backup-git-reuse",
    }
    assert all(path.parent == backup_job_scratch / f"st-backups-{os.getuid()}" and not path.exists() for path in jobs)


@pytest.mark.parametrize("canceled", [False, True])
def test_legacy_infrastructure_download_is_owned_through_validation(backup_job_scratch, monkeypatch, canceled):
    jobs = []

    def download(_command, **kwargs):
        job = Path(kwargs["env"]["TMPDIR"]).parent
        jobs.append(job)
        assert job.parent == backup_job_scratch / f"st-restores-{os.getuid()}"
        kwargs["capacity_check"]()
        (job / "archive.tar.gz.age").write_bytes(b"download fixture")
        if canceled:
            raise backup_activity.BackupCancelled("fixture canceled")
        return subprocess.CompletedProcess([], 0, "", "")

    monkeypatch.setattr(backup_restore_test, "run_bulk_process", download)
    monkeypatch.setattr(backup_restore_test.backup_store, "update_source_restore_test", Mock())
    monkeypatch.setattr(backup_restore_test, "materialize_plaintext_archive", Mock(side_effect=ValueError("fixture validation failure")))
    backup = {"id": "fixture", "location": "//host/share/archive.tar.gz.age"}
    if canceled:
        with pytest.raises(backup_activity.BackupCancelled):
            backup_restore_test._validate_infra_archive("fixture", backup)
    else:
        result = backup_restore_test._validate_infra_archive("fixture", backup)
        assert not result["ok"] and "fixture validation failure" in result["error"]
    assert jobs and not jobs[0].exists()


def test_sqlite_capacity_refusal_precedes_materialization(backup_job_scratch, monkeypatch):
    import sqlite3

    source = backup_job_scratch / "source.sqlite"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE fixture (value TEXT)")
        connection.execute("INSERT INTO fixture VALUES ('recovery')")
    destination = backup_job_scratch / "snapshot.sqlite"
    usage = shutil.disk_usage(backup_job_scratch)
    monkeypatch.setenv("SF_HOST_RETENTION_PRESSURE_MIN_FREE_GB", "25")
    monkeypatch.setattr(scratch.shutil, "disk_usage", lambda _path: usage._replace(free=25 * 1024**3))
    with pytest.raises(scratch.ScratchError):
        recovery._copy_sqlite_database(source, destination)
    assert destination.stat().st_size == 0


def test_download_refuses_unowned_destination_without_deleting_it(tmp_path, monkeypatch):
    unrelated = tmp_path / "unowned"
    unrelated.mkdir(mode=0o700)
    marker = unrelated / "unique-source"
    marker.write_text("preserved")
    network = Mock(side_effect=AssertionError("must not launch"))
    monkeypatch.setattr(backup_restore_test, "run_bulk_process", network)
    with pytest.raises(scratch.ScratchError, match="required scratch mount"):
        backup_restore_test._download_smb_archive("//host/share/archive.age", destination=unrelated)
    assert marker.read_text() == "preserved"
    network.assert_not_called()


def test_download_setup_failure_cleans_its_newly_owned_directory(backup_job_scratch, monkeypatch):
    network = Mock(side_effect=AssertionError("must not launch"))
    monkeypatch.setattr(backup_restore_test, "run_bulk_process", network)
    monkeypatch.setattr(backup_restore_test, "scratch_subprocess_env", Mock(side_effect=scratch.ScratchError("fixture reserve drop")))
    with pytest.raises(scratch.ScratchError, match="fixture reserve drop"):
        backup_restore_test._download_smb_archive("//host/share/archive.age")
    assert not list(backup_job_scratch.glob("st-restores-*/*"))
    network.assert_not_called()
