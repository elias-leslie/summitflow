from __future__ import annotations

import gzip
import io
import json
import os
import shlex
import shutil
import stat
import subprocess
import tarfile
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.utils import transient_scratch


@pytest.fixture(autouse=True)
def synthetic_restore_mount(tmp_path, monkeypatch):
    root = tmp_path / "scratch"
    root.mkdir(mode=0o700)
    monkeypatch.setattr(transient_scratch, "SCRATCH_ROOT", root)
    monkeypatch.setattr(Path, "is_mount", lambda path: path == root)
    usage = shutil.disk_usage(tmp_path)
    monkeypatch.setattr(transient_scratch.shutil, "disk_usage", lambda _path: usage._replace(free=100 * 1024**3))
    return root


@pytest.mark.parametrize("mode,expected", [
    ("start-failed", False),
    ("ping-failed", False),
    ("ping-wrong", False),
    ("dbsize-failed", False),
    ("dbsize-invalid", False),
    ("dbsize-multiline", False),
    ("dbsize-negative", False),
    ("empty", True),
    ("nonempty", True),
])
def test_redis_drill_requires_successful_start_ping_and_numeric_dbsize(
    tmp_path: Path, mode: str, expected: bool,
) -> None:
    from app.tasks import backup_restore_drill

    archive = tmp_path / "infrastructure.tar.gz"
    payload = b"REDIS0009fixture"
    with tarfile.open(archive, "w:gz") as tar:
        member = tarfile.TarInfo("infrastructure/redis-dump.rdb")
        member.size = len(payload)
        tar.addfile(member, io.BytesIO(payload))
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker = fake_bin / "docker"
    docker.write_text("""#!/bin/bash
printf '%s\\n' "$*" >> "$FAKE_DOCKER_LOG"
case "$1" in
    rm) exit 0 ;;
    run) [ "$FAKE_REDIS_MODE" != start-failed ]; exit $? ;;
    exec)
        case "${@: -1}" in
            ping)
                case "$FAKE_REDIS_MODE" in
                    ping-failed) printf 'PONG\\n'; exit 1 ;;
                    ping-wrong) printf 'LOADING\\n'; exit 0 ;;
                    *) printf 'PONG\\n'; exit 0 ;;
                esac ;;
            dbsize)
                case "$FAKE_REDIS_MODE" in
                    dbsize-failed) printf '0\\n'; exit 1 ;;
                    dbsize-invalid) printf 'ERR 123 command failed\\n' ;;
                    dbsize-multiline) printf '1\\n2\\n' ;;
                    dbsize-negative) printf '%s\\n' '-1' ;;
                    empty) printf '0\\n' ;;
                    *) printf '42\\n' ;;
                esac
                exit 0 ;;
        esac ;;
esac
exit 99
""")
    docker.chmod(0o755)
    sleep = fake_bin / "sleep"
    sleep.write_text("#!/bin/sh\nexit 0\n")
    sleep.chmod(0o755)
    log = tmp_path / "docker.log"
    drill_root = tmp_path / "drill"
    drill_root.mkdir(mode=0o700)
    env = {
        **os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "FAKE_REDIS_MODE": mode, "FAKE_DOCKER_LOG": str(log),
        "ST_RESTORE_DRILL_ROOT": str(drill_root), "ST_RESTORE_DRILL_ID": "infra-drill-fixture",
    }
    env.pop("BASH_ENV", None)
    env.pop("ENV", None)

    result = subprocess.run(
        ["bash", str(backup_restore_drill.DRILL_SCRIPT), str(archive)],
        env=env, capture_output=True, text=True, timeout=10, check=False,
    )

    assert result.returncode == 0, result.stderr
    component = next(item for item in json.loads(result.stdout)["components"] if item["key"] == "redis_state")
    assert component["ok"] is expected
    commands = log.read_text().splitlines()
    assert commands[-1].startswith("rm -fv sf-drill-pg-")
    redis_start = next(command for command in commands if command.startswith("run "))
    # Bypass the image's chown and bind all writable Redis data to owned scratch.
    assert "--entrypoint redis-server" in redis_start
    assert f"--user {os.getuid()}:{os.getgid()}" in redis_start
    assert f"source={drill_root}/redis,target=/data" in redis_start
    assert "--network none" in redis_start and "--pull never" in redis_start
    assert (drill_root / "redis/dump.rdb").read_bytes() == payload
    assert stat.S_IMODE((drill_root / "redis").stat().st_mode) == 0o700
    assert "--save" in redis_start
    # With --pull never the drill must use the image the live stack keeps
    # present; an unused image is removed by host image pruning.
    compose = Path(__file__).resolve().parents[3] / "docker" / "compose" / "docker-compose.yml"
    stack_redis_image = next(line.split("image:", 1)[1].strip() for line in compose.read_text().splitlines() if "image: redis:" in line)
    assert f" {stack_redis_image} " in f" {redis_start} "
    if mode in {"start-failed", "ping-failed", "ping-wrong"}:
        assert not any("dbsize" in command for command in commands)
    if mode == "start-failed":
        assert not any(command.startswith("exec") for command in commands)


def test_drill_script_points_to_repo_script() -> None:
    from app.tasks import backup_restore_drill

    expected = Path(__file__).resolve().parents[3] / "scripts" / "infra-restore-drill.sh"

    assert expected == backup_restore_drill.DRILL_SCRIPT
    assert backup_restore_drill.DRILL_SCRIPT.exists()
    assert backup_restore_drill.DRILL_SCRIPT.is_file()


def test_drill_script_keeps_restore_strict_but_skips_bootstrap_postgres_role() -> None:
    from app.tasks import backup_restore_drill

    script = backup_restore_drill.DRILL_SCRIPT.read_text(encoding="utf-8")

    assert "ON_ERROR_STOP=1" in script
    assert "/^CREATE ROLE postgres;$/d" in script
    assert "/^ALTER ROLE postgres /d" in script
    assert '[[ "$ARCHIVE_PATH" == *.age ]]' in script
    assert "umask 077" in script


def test_drill_materializes_encrypted_archive_before_script(monkeypatch) -> None:
    from app.tasks import backup_restore_drill

    encrypted = Path("/tmp/infrastructure.tar.gz.age")
    plaintext = Path("/tmp/infrastructure.tar.gz")
    run_script = MagicMock(return_value={"ok": True, "components": [], "duration_ms": 1})
    monkeypatch.setattr(
        backup_restore_drill,
        "_find_infra_source",
        lambda: {"id": "infrastructure"},
    )
    monkeypatch.setattr(
        backup_restore_drill.backup_store,
        "get_latest_backup",
        lambda **_kwargs: {
            "id": "backup-1",
            "location": str(encrypted),
            "name": encrypted.name,
        },
    )
    monkeypatch.setattr(
        backup_restore_drill,
        "_locate_drill_archive",
        lambda *_args: str(encrypted),
    )
    monkeypatch.setattr(
        backup_restore_drill,
        "materialize_plaintext_archive",
        lambda _path: nullcontext(plaintext),
    )
    monkeypatch.setattr(backup_restore_drill, "_run_drill_script", run_script)
    monkeypatch.setattr(backup_restore_drill, "_record_drill_result", MagicMock())
    monkeypatch.setattr(backup_restore_drill, "_cleanup_temp", MagicMock())

    assert backup_restore_drill.run_infra_drill()["ok"] is True
    run_script.assert_called_once_with(str(plaintext), "backup-1")


@pytest.mark.parametrize("failure", [None, "timeout", "cancel", "capacity", "nonzero"])
def test_drill_wrapper_owns_scratch_and_exact_container_cleanup(
    tmp_path, monkeypatch, synthetic_restore_mount, failure,
):
    from app.tasks import backup_restore_drill as drill
    from app.tasks.backup_activity import BackupCancelled
    from app.utils.transient_scratch import ScratchError

    archive_path = tmp_path / "archive.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        member = tarfile.TarInfo("infrastructure/readme")
        member.size = 7
        archive.addfile(member, io.BytesIO(b"fixture"))
    jobs = []
    removed = []
    before = os.environ.get("TMPDIR")

    def execute(command, **kwargs):
        job = Path(kwargs["env"]["ST_RESTORE_DRILL_ROOT"])
        jobs.append(job)
        assert job.parent.parent == synthetic_restore_mount
        assert kwargs["env"]["TMPDIR"] == str(job)
        assert kwargs["timeout"] == drill.DRILL_TIMEOUT
        assert stat.S_IMODE(job.stat().st_mode) == 0o700
        (job / "plaintext").write_bytes(b"fixture")
        if failure == "timeout":
            raise subprocess.TimeoutExpired(command, drill.DRILL_TIMEOUT)
        if failure == "cancel":
            raise BackupCancelled("fixture cancellation")
        kwargs["capacity_check"]()
        return subprocess.CompletedProcess(command, 23 if failure == "nonzero" else 0, stdout='{"ok":true,"components":[]}', stderr="")

    def cleanup(command, **_kwargs):
        removed.append(command)
        assert jobs[0].exists()
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(drill, "run_bulk_process", execute)
    monkeypatch.setattr(drill.subprocess, "run", cleanup)
    if failure == "capacity":
        monkeypatch.setattr(drill, "ensure_scratch_capacity", MagicMock(side_effect=ScratchError("fixture reserve crossed")))
    if failure in {"timeout", "cancel", "capacity"}:
        error = {"timeout": subprocess.TimeoutExpired, "cancel": BackupCancelled, "capacity": ScratchError}[failure]
        with pytest.raises(error):
            drill._run_drill_script(str(archive_path), "fixture-backup")
    else:
        assert drill._run_drill_script(str(archive_path), "fixture-backup")["ok"] is (failure is None)
    assert removed == [["docker", "rm", "-fv", f"sf-drill-pg-{jobs[0].name}", f"sf-drill-redis-{jobs[0].name}"]]
    assert not jobs[0].exists()
    assert os.environ.get("TMPDIR") == before


def test_drill_capacity_accounts_extraction_and_redis_copy_before_script(tmp_path, monkeypatch):
    from app.tasks import backup_restore_drill as drill
    from app.utils.transient_scratch import ScratchError

    path = tmp_path / "archive.tar.gz"
    with tarfile.open(path, "w:gz") as archive:
        member = tarfile.TarInfo("infrastructure/redis-dump.rdb")
        member.size = 12
        archive.addfile(member, io.BytesIO(b"REDISfixture"))
    capacities = []

    def refuse(_path, required):
        capacities.append(required)
        raise ScratchError("fixture insufficient capacity")

    monkeypatch.setattr(transient_scratch, "ensure_scratch_capacity", refuse)
    execute = MagicMock()
    monkeypatch.setattr(drill, "run_bulk_process", execute)
    with pytest.raises(ScratchError):
        drill._run_drill_script(str(path), "fixture")
    assert capacities == [24]
    execute.assert_not_called()


def test_drill_cleanup_failure_preserves_cancellation_and_records_note(tmp_path, monkeypatch):
    from app.tasks import backup_restore_drill as drill
    from app.tasks.backup_activity import BackupCancelled

    path = tmp_path / "archive.tar.gz"
    with tarfile.open(path, "w:gz") as archive:
        member = tarfile.TarInfo("infrastructure")
        member.type = tarfile.DIRTYPE
        archive.addfile(member)
    cancelled = BackupCancelled("fixture cancellation")
    monkeypatch.setattr(drill, "run_bulk_process", MagicMock(side_effect=cancelled))
    monkeypatch.setattr(drill, "_remove_drill_containers", MagicMock(side_effect=RuntimeError("fixture cleanup failure")))
    with pytest.raises(BackupCancelled) as observed:
        drill._run_drill_script(str(path), "fixture")
    assert "cleanup also failed" in observed.value.__notes__[0]


@pytest.mark.parametrize("remaining", ["gone", "present", "unavailable"])
def test_failed_container_removal_verifies_exact_attempt_and_reports_unknown(monkeypatch, remaining):
    from app.tasks import backup_restore_drill as drill

    calls = []

    def docker(command, **_kwargs):
        calls.append(command)
        if command[1] == "rm":
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="")
        return subprocess.CompletedProcess(command, 1 if remaining == "unavailable" else 0,
                                           stdout="sf-drill-pg-fixture" if remaining == "present" else "", stderr="")

    monkeypatch.setattr(drill.subprocess, "run", docker)
    names = ["sf-drill-pg-fixture", "sf-drill-redis-fixture"]
    if remaining == "gone":
        drill._remove_drill_containers(names)
    else:
        with pytest.raises(RuntimeError, match=r"cleanup|remain"):
            drill._remove_drill_containers(names)
    assert calls[0] == ["docker", "rm", "-fv", *names]
    assert calls[1][3:5] == ["--filter", "name=^/(sf-drill-pg-fixture|sf-drill-redis-fixture)$"]


@pytest.mark.parametrize("failure", [False, True])
def test_smb_download_uses_owned_scratch_and_cleans_success_or_timeout(
    monkeypatch, synthetic_restore_mount, failure,
):
    from app.tasks import backup_restore_drill as drill

    jobs = []

    def download(command, **kwargs):
        destination = Path(shlex.split(command[-1].split("; ")[-1])[-1])
        jobs.append(destination.parent)
        assert destination.parent.parent.parent == synthetic_restore_mount
        assert kwargs["timeout"] == drill.SMB_DOWNLOAD_TIMEOUT
        assert Path(kwargs["env"]["TMPDIR"]).is_relative_to(destination.parent)
        kwargs["capacity_check"]()
        destination.write_bytes(b"fixture archive")
        if failure:
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(drill, "run_bulk_process", download)
    downloaded = drill._download_from_smb("//fixture/share/backups/archive.tar.gz")
    if failure:
        assert downloaded is None
    else:
        assert downloaded is not None
        assert stat.S_IMODE(Path(downloaded).stat().st_mode) == 0o600
        # Downloads inferred from SMB configuration also clean up when the
        # original location was empty rather than an explicit // reference.
        drill._cleanup_temp(downloaded, "")
    assert not jobs[0].exists()


@pytest.mark.parametrize("init_completes", [True, False])
def test_postgres_drill_waits_for_init_restart_before_loading(tmp_path: Path, init_completes: bool) -> None:
    from app.tasks import backup_restore_drill

    archive = tmp_path / "infrastructure.tar.gz"
    dump = io.BytesIO(gzip.compress(b"SELECT 1;\n"))
    with tarfile.open(archive, "w:gz") as tar:
        member = tarfile.TarInfo("infrastructure/pgdumpall.sql.gz")
        member.size = len(dump.getvalue())
        tar.addfile(member, io.BytesIO(dump.getvalue()))
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    state = tmp_path / "logs-calls"
    # pg_isready always succeeds (the temporary init server answers it); the
    # init-complete marker only appears on the third log read, if at all.
    (fake_bin / "docker").write_text(f"""#!/bin/bash
printf '%s\\n' "$*" >> "$FAKE_DOCKER_LOG"
case "$1" in
    rm|run) exit 0 ;;
    logs)
        n=$(( $(cat {state} 2>/dev/null || echo 0) + 1 )); echo $n > {state}
        [ "$FAKE_INIT" = 1 ] && [ $n -ge 3 ] && echo "PostgreSQL init process complete; ready for start up."
        exit 0 ;;
    exec)
        case "$*" in
            *pg_isready*) exit 0 ;;
            *-tAc*) printf '3\\n'; exit 0 ;;
            *psql*) cat >/dev/null; exit 0 ;;
        esac ;;
esac
exit 99
""")
    (fake_bin / "docker").chmod(0o755)
    (fake_bin / "sleep").write_text("#!/bin/sh\nexit 0\n")
    (fake_bin / "sleep").chmod(0o755)
    log = tmp_path / "docker.log"
    drill_root = tmp_path / "drill"
    drill_root.mkdir(mode=0o700)
    env = {
        **os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}", "FAKE_DOCKER_LOG": str(log),
        "FAKE_INIT": "1" if init_completes else "0",
        "ST_RESTORE_DRILL_ROOT": str(drill_root), "ST_RESTORE_DRILL_ID": "infra-drill-fixture",
    }
    env.pop("BASH_ENV", None)
    env.pop("ENV", None)

    result = subprocess.run(
        ["bash", str(backup_restore_drill.DRILL_SCRIPT), str(archive)],
        env=env, capture_output=True, text=True, timeout=30, check=False,
    )

    component = next(item for item in json.loads(result.stdout)["components"] if item["key"] == "postgres_dump")
    commands = log.read_text().splitlines()
    loads = [index for index, command in enumerate(commands) if command.startswith("exec -i ")]
    if init_completes:
        assert component["ok"] is True
        assert len(loads) == 1
        assert sum(command.startswith("logs ") for command in commands[: loads[0]]) == 3
    else:
        assert component["ok"] is False
        assert component["error"].startswith("Disposable PostgreSQL did not become ready")
        assert loads == []
