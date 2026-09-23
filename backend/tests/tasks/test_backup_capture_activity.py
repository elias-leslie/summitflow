"""Capture cancellation and streaming preserve the existing recovery contract."""

import gzip
import io
import sqlite3
import subprocess
import sys
import tarfile
from pathlib import Path
from typing import Any

import pytest


def test_gzip_dump_uses_streaming_bulk_runner_and_preserves_child_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tasks import backup_native_archive as archive

    def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        assert kwargs["attention_after"] == 0.01
        assert kwargs["text"] is False
        kwargs["stdout_sink"](io.BytesIO(b"transactionally consistent dump"))
        return subprocess.CompletedProcess(command, 7, b"", b"real child error")

    monkeypatch.setattr(archive, "run_bulk_process", run, raising=False)
    destination = tmp_path / "dump.sql.gz"
    result = archive._run_gzip_stream(["fixture-dump"], destination, env=None, timeout=0.01)
    assert result == (7, b"real child error")
    assert gzip.decompress(destination.read_bytes()) == b"transactionally consistent dump"


def test_git_bundle_uses_bulk_runner_not_metadata_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tasks import backup_native_recovery as recovery

    calls: list[list[str]] = []

    def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        assert kwargs["attention_after"] == 120
        return subprocess.CompletedProcess(command, 0, "done", "")

    monkeypatch.setattr(recovery, "run_bulk_process", run, raising=False)
    result = recovery._run_git(tmp_path, ["bundle", "create", "backup.bundle", "--all"])
    assert result.returncode == 0
    assert calls == [["git", "-C", str(tmp_path), "bundle", "create", "backup.bundle", "--all"]]


def test_snapshot_stops_before_copy_when_cancelled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tasks import backup_native_recovery as recovery

    class StopCapture(BaseException):
        pass

    source = tmp_path / "source"
    source.mkdir()
    (source / "valuable.txt").write_text("preserve")
    inventory = recovery.inventory_project_tree(source, (), lambda *_: False)
    destination = tmp_path / "snapshot"

    def stop() -> None:
        raise StopCapture

    monkeypatch.setattr(recovery, "check_backup_cancelled", stop, raising=False)
    with pytest.raises(StopCapture):
        recovery.copy_inventory_snapshot(source, destination, inventory)
    assert not (destination / "valuable.txt").exists()
    assert (source / "valuable.txt").read_text() == "preserve"


def test_gzip_dump_drains_large_stderr_without_buffer_deadlock(tmp_path: Path) -> None:
    from app.tasks import backup_native_archive as archive

    destination = tmp_path / "dump.sql.gz"
    result = archive._run_gzip_stream(
        [sys.executable, "-c", "import sys; sys.stderr.write('e'*262144); print('dump')"],
        destination, env=None, timeout=1,
    )
    assert result[0] == 0
    assert result[1] == b"e" * 500
    assert gzip.decompress(destination.read_bytes()) == b"dump\n"


def test_slow_healthy_dump_is_not_killed_by_attention_budget(tmp_path: Path) -> None:
    from app.tasks import backup_native_archive as archive

    destination = tmp_path / "dump.sql.gz"
    result = archive._run_gzip_stream(
        [sys.executable, "-c", "import time; time.sleep(0.05); print('dump')"],
        destination, env=None, timeout=0.01,
    )
    assert result[0] == 0
    assert gzip.decompress(destination.read_bytes()) == b"dump\n"


def test_jsonl_cancellation_is_not_misreported_as_source_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tasks import backup_native_recovery as recovery
    from app.tasks.backup_activity import BackupCancelled

    source = tmp_path / "events.jsonl"
    source.write_bytes(b"first\nsecond\n")
    inventory = recovery.inventory_project_tree(tmp_path, (), lambda *_: False)

    def stop() -> None:
        raise BackupCancelled("owner cancelled")

    monkeypatch.setattr(recovery, "check_backup_cancelled", stop)
    with pytest.raises(BackupCancelled, match="owner cancelled"):
        recovery._copy_jsonl_prefix(source, tmp_path / "snapshot", inventory[source.name], source.name)
    assert source.read_bytes() == b"first\nsecond\n"


def test_sqlite_online_backup_checks_cancellation_between_batches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tasks import backup_native_recovery as recovery
    from app.tasks.backup_activity import BackupCancelled

    source = tmp_path / "state.sqlite"
    with sqlite3.connect(source) as db:
        db.execute("CREATE TABLE durable (content BLOB)")
        db.execute("INSERT INTO durable VALUES (zeroblob(2097152))")
    calls = 0

    def check() -> None:
        nonlocal calls
        calls += 1
        if calls >= 2:
            raise BackupCancelled("owner cancelled")

    monkeypatch.setattr(recovery, "check_backup_cancelled", check)
    with pytest.raises(BackupCancelled):
        recovery._copy_sqlite_database(source, tmp_path / "copy.sqlite")
    assert calls == 2
    with sqlite3.connect(source) as db:
        assert db.execute("SELECT length(content) FROM durable").fetchone()[0] == 2097152


def test_large_tar_member_has_mid_member_cancellation_checkpoints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tasks import backup_native_archive as archive
    from app.tasks.backup_activity import BackupCancelled

    source = tmp_path / "large.bin"
    source.write_bytes(b"x" * 1048576)
    calls = 0

    def check() -> None:
        nonlocal calls
        calls += 1
        if calls >= 3:
            raise BackupCancelled("owner cancelled")

    monkeypatch.setattr(archive, "check_backup_cancelled", check)
    with tarfile.open(tmp_path / "snapshot.tar", "w") as output, pytest.raises(BackupCancelled):
        archive._add_checked_file(output, source, "source/large.bin")
    assert calls == 3


def test_gzip_cancellation_reaps_child_before_returning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tasks import backup_activity
    from app.tasks import backup_native_archive as archive

    processes: list[subprocess.Popen[Any]] = []
    original = subprocess.Popen

    def popen(*args: Any, **kwargs: Any) -> subprocess.Popen[Any]:
        proc = original(*args, **kwargs)
        processes.append(proc)
        return proc

    class Activity:
        def start_phase(self, *_args: Any) -> None:
            pass

        def check_cancelled(self) -> None:
            raise backup_activity.BackupCancelled("owner cancelled")

    monkeypatch.setattr(backup_activity, "current_activity", lambda: Activity())
    monkeypatch.setattr(backup_activity.subprocess, "Popen", popen)
    with pytest.raises(backup_activity.BackupCancelled):
        archive._run_gzip_stream(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            tmp_path / "dump.gz", env=None, timeout=600,
        )
    assert len(processes) == 1
    assert processes[0].poll() is not None
