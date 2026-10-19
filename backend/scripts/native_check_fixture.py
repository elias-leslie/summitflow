"""Canonical native stages over a bounded, empty, network-isolated PostgreSQL fixture."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # run as a script, only scripts/ is on the path

import json
import os
import secrets
import signal
import subprocess
import tempfile
import time
from contextlib import contextmanager
from urllib.parse import urlsplit
from uuid import uuid4

import psycopg

from cli.lib.ci_parity import container_cli

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
IMAGE_LOCK = Path(__file__).with_name("native_fixture_image.txt")
# The prior 1560s pytest budget exhausted after a previous 1373.5s full
# suite. 1860s adds 19.2% headroom over that observed exhaustion.
PYTHON_TEST_TIMEOUT_SECONDS = 1860
BOOTSTRAP_TIMEOUT_SECONDS = 180
PYTHON_TEST_WORKERS = max(1, min(8, (os.cpu_count() or 2) // 2))
READINESS_TIMEOUT_SECONDS = 60
CONTAINER_TIMEOUT_SECONDS = 30
# Keep bootstrap, readiness and one container cleanup operation inside the
# watchdog. The outer Python stage also reserves three container setup operations.
LIFETIME_SECONDS = (PYTHON_TEST_TIMEOUT_SECONDS + BOOTSTRAP_TIMEOUT_SECONDS
                    + READINESS_TIMEOUT_SECONDS + CONTAINER_TIMEOUT_SECONDS)
FLEET_LIFETIME_SECONDS = 1800


def engine_command() -> tuple[list[str], bool] | None:
    """container_cli(), reaching the user's podman socket from a stage environment that drops XDG_RUNTIME_DIR."""
    runtime = f"/run/user/{os.getuid()}"
    if os.path.isdir(runtime):
        os.environ.setdefault("XDG_RUNTIME_DIR", runtime)
    return container_cli()


def container(*arguments: str, environment: dict[str, str] | None = None) -> str:
    """Run the container CLI: docker when reachable, else this user's rootless podman (see container_cli)."""
    engine = engine_command()
    if engine is None:
        raise RuntimeError("Isolated PostgreSQL fixture needs docker or rootless podman")
    result = subprocess.run(
        [*engine[0], *arguments], env=environment, capture_output=True, text=True,
        timeout=CONTAINER_TIMEOUT_SECONDS, check=False,
    )
    if result.returncode:
        # Never include container environment/credentials in retained diagnostics.
        raise RuntimeError(f"Isolated PostgreSQL fixture container operation failed: {arguments[0]}")
    return result.stdout.strip()


@contextmanager
def database_fixture(*, lifetime_seconds: int = LIFETIME_SECONDS):
    """Only this invocation's named fixture is created or removed; no host DB access."""
    if not 60 <= lifetime_seconds <= LIFETIME_SECONDS:
        raise RuntimeError("Fixture lifetime exceeds the canonical native stage bound")
    # Line 1 is the immutable image ID; line 2, when present, is the registry reference to pull it from.
    image, _, reference = IMAGE_LOCK.read_text().strip().partition("\n")
    image = image.strip()
    if not image.startswith("sha256:") or len(image) != 71:
        raise RuntimeError("Fixture image must be pinned to a full immutable local image ID")
    try:
        prepared = container("image", "inspect", image, "--format", "{{.Id}}").removeprefix("sha256:")
    except RuntimeError:
        prepared = ""
    if prepared != image.removeprefix("sha256:"):
        pull = f"podman pull {reference.strip()}" if reference.strip() else "pull the locked image"
        raise RuntimeError(f"Prepared PostgreSQL fixture image unavailable; preparation must be explicit ({pull})")
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
    mapping = os.environ.get("ST_NATIVE_TMP_HOST_ROOT")
    # A scratch mapping translates this process's private /tmp to its host
    # backing path, so the socket must live there whatever TMPDIR names.
    temporary = tempfile.TemporaryDirectory(prefix="st-native-db-", dir="/tmp" if mapping else None)
    try:
        directory = Path(temporary.name)
        socket = directory / "socket"
        socket.mkdir(mode=0o777)
        socket.chmod(0o777)
        host_socket = socket
        if mapping:
            host_root = Path(mapping)
            if (not host_root.is_absolute() or ".." in host_root.parts or host_root == Path("/tmp")
                    or not host_root.is_dir() or host_root.resolve() != host_root):
                raise RuntimeError("Invalid native scratch mapping")
            if not socket.is_relative_to("/tmp"):
                raise RuntimeError("Native scratch mapping requires a private /tmp socket")
            host_socket = host_root / socket.relative_to("/tmp")
        # Rootless podman rejects tmpfs uid=/gid= options; its U flag hands the mount to --user instead.
        engine = engine_command()
        data = (["--mount", "type=tmpfs,destination=/var/lib/postgresql/data,tmpfs-mode=0700,U=true"]
                if engine and engine[1]
                else ["--tmpfs", "/var/lib/postgresql/data:rw,uid=999,gid=999,mode=0700"])
        home = directory / "home"
        home.mkdir()
        password = secrets.token_urlsafe(32)
        environment = {**os.environ, "POSTGRES_PASSWORD": password}
        # The in-container watchdog also expires a fixture after SIGKILL or
        # host stage timeout, when Python cannot execute its finally block.
        command = (f"(sleep {lifetime_seconds}; kill -TERM 1) & "
                   "exec /usr/local/bin/docker-entrypoint.sh postgres "
                   "-c listen_addresses='' -c unix_socket_directories=/var/run/postgresql")
        container("create", "--pull", "never", "--name", name, "--label", "summitflow.native-fixture=true",
               "--network", "none", "--read-only", "--user", "999:999",
               *data,
               "--mount", f"type=bind,source={host_socket},target=/var/run/postgresql",
               "--env", "POSTGRES_DB=summitflow_test", "--env", "POSTGRES_USER=summitflow_app",
               "--env", "POSTGRES_PASSWORD", "--entrypoint", "/bin/sh", image,
               "-c", command, environment=environment)
        record("created")
        container("start", name)
        # tempfile's fixed prefix and generated suffix need no URL escaping;
        # avoiding percent escapes also supports Alembic's ConfigParser URL.
        url = f"postgresql://summitflow_app:{password}@/summitflow_test?host={socket}"
        deadline = time.monotonic() + READINESS_TIMEOUT_SECONDS
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
            container("rm", "--force", name)
            record("removed")
        except RuntimeError:
            record("cleanup_unavailable_watchdog_bounded")
            raise
        finally:
            signal.signal(signal.SIGTERM, previous)
            temporary.cleanup()


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) == 2 else ""
    if mode not in {"bootstrap", "python", "fleet", "deep"}:
        raise SystemExit("Usage: native_check_fixture.py bootstrap|python|fleet|deep")
    full_suite = mode in {"python", "deep"}
    lifetime_seconds = (BOOTSTRAP_TIMEOUT_SECONDS + CONTAINER_TIMEOUT_SECONDS if mode == "bootstrap"
                        else LIFETIME_SECONDS if full_suite else FLEET_LIFETIME_SECONDS)
    with database_fixture(lifetime_seconds=lifetime_seconds) as environment:
        bootstrap = subprocess.run(
            [sys.executable, str(BACKEND / "scripts" / "verify_bootstrap_schema.py")],
            cwd=BACKEND, env=environment, capture_output=True, text=True,
            timeout=BOOTSTRAP_TIMEOUT_SECONDS, check=False,
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
        report = ROOT / ".dev-tools" / f"native-{mode}.xml"
        tests = ["tests"] if full_suite else [
            "tests/storage/test_fleet_events.py", "tests/services/test_fleet_sessions.py",
            "tests/cli/test_sessions_fleet.py", "tests/api/test_fleet_sessions.py",
            "tests/cli/test_sessions.py", "tests/cli/test_sessions_close.py",
            "tests/storage/test_maintenance_retention.py", "tests/test_events_api_filters.py",
        ]
        # Each xdist worker bootstraps its own database in this superuser fixture.
        workers = ["-n", str(PYTHON_TEST_WORKERS), "--dist", "worksteal"] if full_suite else []
        # The nightly deep lane runs what the gate's addopts exclude, except
        # e2e, which targets the deployed service.
        markers = ["-m", "slow and not e2e"] if mode == "deep" else []
        # Acceptance pins pytest-randomly's order so `st check --ci-repro --seed N` replays it.
        seed = [f"--randomly-seed={os.environ['ST_CHECK_SEED']}"] if os.environ.get("ST_CHECK_SEED", "").isdigit() else []
        # Direct stages keep TMPDIR on deep mounted scratch. A short private
        # base keeps tests' tmp_path AF_UNIX sockets within the 108-byte limit
        # without moving bulk temporary files off that scratch.
        basetemp = tempfile.TemporaryDirectory(prefix="", ignore_cleanup_errors=True)
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pytest", *tests, *workers, *markers, *seed, "--junitxml=" + str(report),
                 "--basetemp=" + basetemp.name,
                 "--deselect=tests/cli/test_saved_work_snapshots.py::test_native_btrfs_shared_capture_readonly_recovery_and_isolated_restore",
                 "--deselect=tests/cli/test_saved_work_snapshots.py::test_native_nested_saved_source_is_refused_and_disposable_tracked_fixture_preserved",
                 "-k", "not test_live_owner_lease_proxy_preserves_same_target_and_blocks_resume "
                 "and not test_real_detached_result_survives_collection "
                 "and not (test_pre_push_chains_same_arguments_and_stdin and global)"],
                cwd=BACKEND, env=environment,
                timeout=PYTHON_TEST_TIMEOUT_SECONDS if full_suite else FLEET_LIFETIME_SECONDS - 240,
                capture_output=True, text=True, check=False,
            )
        finally:
            basetemp.cleanup()
        print(result.stdout.replace(password, "[fixture credential]"), end="")
        print(result.stderr.replace(password, "[fixture credential]"), file=sys.stderr, end="")
        if report.is_file():
            report.write_text(report.read_text().replace(password, "[fixture credential]"))
        # pytest exits 5 when nothing is marked slow: nothing opted in yet.
        return 0 if mode == "deep" and result.returncode == 5 else result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
