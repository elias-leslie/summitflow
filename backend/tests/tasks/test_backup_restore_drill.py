from __future__ import annotations

import io
import json
import os
import subprocess
import tarfile
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import MagicMock

import pytest


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
    env = {
        **os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "FAKE_REDIS_MODE": mode, "FAKE_DOCKER_LOG": str(log),
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
    # The image entrypoint chowns /data; a read-only recovered RDB must not be
    # changed, even when testing as root. Match the recovery user's file access.
    assert "--entrypoint redis-server" in redis_start
    assert f"--user {os.getuid()}:{os.getgid()}" in redis_start
    assert "/data/dump.rdb:ro" in redis_start
    assert "--save" in redis_start
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
