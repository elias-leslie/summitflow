"""Canonical native stages over a bounded, empty, network-isolated PostgreSQL fixture."""

from __future__ import annotations

import json
import os
import secrets
import signal
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import psycopg

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
IMAGE_LOCK = Path(__file__).with_name("native_fixture_image.txt")
LIFETIME_SECONDS = 1800
DOCKER = "/usr/bin/docker"


def docker(*arguments: str, environment: dict[str, str] | None = None) -> str:
    result = subprocess.run(
        [DOCKER, *arguments], env=environment, capture_output=True, text=True,
        timeout=30, check=False,
    )
    if result.returncode:
        # Never include container environment/credentials in retained diagnostics.
        raise RuntimeError(f"Isolated PostgreSQL fixture Docker operation failed: {arguments[0]}")
    return result.stdout.strip()


@contextmanager
def database_fixture(*, lifetime_seconds: int = LIFETIME_SECONDS):
    """Only this invocation's named fixture is created or removed; no host DB access."""
    if not 60 <= lifetime_seconds <= LIFETIME_SECONDS:
        raise RuntimeError("Fixture lifetime exceeds the canonical native stage bound")
    image = IMAGE_LOCK.read_text().strip()
    if not image.startswith("sha256:") or len(image) != 71:
        raise RuntimeError("Fixture image must be pinned to a full immutable local image ID")
    if docker("image", "inspect", image, "--format", "{{.Id}}") != image:
        raise RuntimeError("Prepared PostgreSQL fixture image unavailable; preparation must be explicit")
    name = "st-native-db-" + uuid4().hex
    ledger_dir = ROOT / ".dev-tools" / "native-fixtures"
    ledger_dir.mkdir(parents=True, exist_ok=True)
    ledger = ledger_dir / (name + ".json")
    identity = {"container": name, "image": image, "maximum_lifetime_seconds": lifetime_seconds,
                "network": "none", "data": "disposable_tmpfs"}

    def record(state: str) -> None:
        ledger.write_text(json.dumps({**identity, "state": state}, sort_keys=True) + "\n")

    previous = signal.getsignal(signal.SIGTERM)

    def interrupted(_signum, _frame):
        raise InterruptedError("Native PostgreSQL fixture interrupted")

    signal.signal(signal.SIGTERM, interrupted)
    record("creating")
    temporary = tempfile.TemporaryDirectory(prefix="st-native-db-")
    try:
        directory = Path(temporary.name)
        socket = directory / "socket"
        socket.mkdir(mode=0o777)
        socket.chmod(0o777)
        home = directory / "home"
        home.mkdir()
        password = secrets.token_urlsafe(32)
        environment = {**os.environ, "POSTGRES_PASSWORD": password}
        # The in-container watchdog also expires a fixture after SIGKILL or
        # host stage timeout, when Python cannot execute its finally block.
        command = (f"(sleep {lifetime_seconds}; kill -TERM 1) & "
                   "exec /usr/local/bin/docker-entrypoint.sh postgres "
                   "-c listen_addresses='' -c unix_socket_directories=/var/run/postgresql")
        docker("create", "--pull", "never", "--name", name, "--label", "summitflow.native-fixture=true",
               "--network", "none", "--read-only", "--user", "999:999",
               "--tmpfs", "/var/lib/postgresql/data:rw,uid=999,gid=999,mode=0700",
               "--mount", f"type=bind,source={socket},target=/var/run/postgresql",
               "--env", "POSTGRES_DB=summitflow_test", "--env", "POSTGRES_USER=summitflow_app",
               "--env", "POSTGRES_PASSWORD", "--entrypoint", "/bin/sh", image,
               "-c", command, environment=environment)
        record("created")
        docker("start", name)
        # tempfile's fixed prefix and generated suffix need no URL escaping;
        # avoiding percent escapes also supports Alembic's ConfigParser URL.
        url = f"postgresql://summitflow_app:{password}@/summitflow_test?host={socket}"
        deadline = time.monotonic() + 60
        while True:
            try:
                with psycopg.connect(url, connect_timeout=1) as connection:
                    tables = connection.execute(
                        "SELECT count(*) FROM pg_tables WHERE schemaname='public'"
                    ).fetchone()
                    if tables != (0,):
                        raise RuntimeError("New PostgreSQL fixture was not entirely empty")
                break
            except psycopg.OperationalError:
                if time.monotonic() >= deadline:
                    raise RuntimeError("Isolated PostgreSQL fixture did not become ready") from None
                time.sleep(0.2)
        record("ready")
        # No operator home dotenv or production database/admin credentials.
        yield {**os.environ, "HOME": str(home), "XDG_STATE_HOME": str(directory / "state"),
               "DATABASE_URL": url, "TEST_DATABASE_URL": url, "DATABASE_ADMIN_URL": "",
               "POSTGRES_ADMIN_URL": "", "REDIS_URL": "redis://127.0.0.1:1",
               "AGENT_HUB_URL": "http://127.0.0.1:1", "PYTHONPATH": str(BACKEND)}
    finally:
        try:
            docker("rm", "--force", name)
            record("removed")
        except RuntimeError:
            record("cleanup_unavailable_watchdog_bounded")
            raise
        finally:
            signal.signal(signal.SIGTERM, previous)
            temporary.cleanup()


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) == 2 else ""
    if mode not in {"bootstrap", "python"}:
        raise SystemExit("Usage: native_check_fixture.py bootstrap|python")
    with database_fixture(lifetime_seconds=210 if mode == "bootstrap" else LIFETIME_SECONDS) as environment:
        bootstrap = subprocess.run(
            [sys.executable, str(BACKEND / "scripts" / "verify_bootstrap_schema.py")],
            cwd=BACKEND, env=environment, capture_output=True, text=True, timeout=180, check=False,
        )
        password = urlsplit(environment["DATABASE_URL"]).password
        assert password
        print(bootstrap.stdout.replace(password, "[fixture credential]"), file=sys.stderr, end="")
        print(bootstrap.stderr.replace(password, "[fixture credential]"), file=sys.stderr, end="")
        if bootstrap.returncode:
            return bootstrap.returncode
        if mode == "bootstrap":
            print(json.dumps({"passed": 1, "failed": 0, "skipped": 0}))
            return 0
        report = ROOT / ".dev-tools" / "native-python.xml"
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "tests", "--junitxml=" + str(report),
             "-k", "not test_live_owner_lease_proxy_preserves_same_target_and_blocks_resume "
             "and not test_real_detached_result_survives_collection "
             "and not (test_pre_push_chains_same_arguments_and_stdin and global)"],
            cwd=BACKEND, env=environment, timeout=LIFETIME_SECONDS - 240,
            capture_output=True, text=True, check=False,
        )
        print(result.stdout.replace(password, "[fixture credential]"), end="")
        print(result.stderr.replace(password, "[fixture credential]"), file=sys.stderr, end="")
        if report.is_file():
            report.write_text(report.read_text().replace(password, "[fixture credential]"))
        return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
