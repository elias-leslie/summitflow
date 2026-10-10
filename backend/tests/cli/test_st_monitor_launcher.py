"""The installed monitor entry point survives a missing backend environment."""

from __future__ import annotations

import gzip
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest


@pytest.fixture
def installed(tmp_path: Path):
    source = Path(__file__).resolve().parents[3]
    root = tmp_path / "checkout"
    (root / "scripts").mkdir(parents=True)
    (root / "backend" / "monitor_reader").mkdir(parents=True)
    (root / "backend" / "monitor_control").mkdir(parents=True)
    (root / "backend" / "cli").mkdir(parents=True)
    shutil.copytree(source / "backend" / "monitor_observe", root / "backend" / "monitor_observe",
                    ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(source / "backend" / "monitor_extended", root / "backend" / "monitor_extended",
                    ignore=shutil.ignore_patterns("__pycache__"))
    for relative in ("scripts/st", "backend/monitor_standalone.py", "backend/monitor_control/__init__.py",
                     "backend/monitor_reader/__init__.py", "backend/monitor_reader/reader.py"):
        shutil.copy2(source / relative, root / relative)
    (root / "project.identity.json").write_text(json.dumps({
        "project": {"id": "summitflow"},
        "services": {"backend": "summitflow-backend.service", "frontend": "summitflow-frontend.service",
                     "default_workers": [], "optional_workers": []},
    }))
    (root / "backend" / "cli" / "main.py").write_text("raise RuntimeError('backend import graph is broken')\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    link = bin_dir / "st"
    link.symlink_to(root / "scripts" / "st")
    # A pytest node directory plus state suffix can exceed AF_UNIX sun_path.
    # Keep the same protocol fixture in a short private root with teardown.
    with tempfile.TemporaryDirectory(prefix="st-m-", dir="/tmp") as directory:
        state = Path(directory) / "summitflow" / "monitor"
        state.mkdir(parents=True)
        env = {**os.environ, "SUMMITFLOW_MONITOR_STATE_DIR": str(state),
               "SUMMITFLOW_SERVICE_STATE_ROOT": str(tmp_path / "isolated-services"), "PYTHONNOUSERSITE": "1"}
        yield root, link, state, env


def _run(link: Path, env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(link), *args], env=env, text=True, capture_output=True, check=False)


@contextmanager
def _observations(state: Path, count: int):
    """A collector socket proves the standalone CLI uses the privileged protocol."""
    received = []
    path = state / "control.sock"
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(str(path))
        server.listen(count)
        server.settimeout(3)

        def serve() -> None:
            for _ in range(count):
                connection, _ = server.accept()
                with connection:
                    with connection.makefile("rb") as stream:
                        request = json.loads(stream.readline())
                    received.append(request)
                    source = request["source"]
                    params = request["params"]
                    value = ({"message": "token=[REDACTED]"} if source == "logs" else
                             {"local": "127.0.0.1:8080"} if source == "connections" else
                             {"name": "visible.txt", "apparent_bytes": 5})
                    result = {"schema": 1, "generated_at": datetime.now(UTC).isoformat(),
                              "requested": {"kind": source, **params},
                              "coverage": {"scope": "mount", "complete": False},
                              "items": [{"value": value}], "next_cursor": None,
                              "truncated": False, "errors": []}
                    response = {"schema": 1, "ok": True, "result": result}
                    connection.sendall((json.dumps(response) + "\n").encode())

        worker = threading.Thread(target=serve, daemon=True)
        worker.start()
        try:
            yield received
        finally:
            worker.join(timeout=3)
            assert not worker.is_alive()


def test_installed_monitor_prefers_accepted_release_source(installed, tmp_path: Path) -> None:
    root, link, state, env = installed
    _store(state)
    (root / "visible.txt").write_text("visible")
    service_state = tmp_path / "managed-services"
    accepted = service_state / "projects/summitflow/current/source"
    shutil.copytree(root / "backend", accepted / "backend")
    (root / "backend/monitor_standalone.py").write_text("raise RuntimeError('checkout monitor is newer')\n")
    env["SUMMITFLOW_SERVICE_STATE_ROOT"] = str(service_state)
    result = _run(link, env, "monitor", "status")
    assert result.returncode == 0
    assert json.loads(result.stdout)["schema"] == 1
    with _observations(state, 1) as received:
        disk = _run(link, env, "monitor", "disk-space", str(root), "--limit", "5")
    assert disk.returncode == 0, disk.stderr or disk.stdout
    assert json.loads(disk.stdout)["coverage"]["scope"] == "mount"
    assert received[0]["params"]["path"] == str(root)


def _store(state: Path) -> None:
    now = int(datetime.now(UTC).timestamp() * 1_000_000_000)
    with sqlite3.connect(state / "monitor.sqlite3") as conn:
        conn.executescript("""
            CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            INSERT INTO meta VALUES('schema_version','1');
            INSERT INTO meta VALUES('host_id','host-a');
            CREATE TABLE samples(id INTEGER PRIMARY KEY,sampled_at_ns INTEGER NOT NULL,
              monotonic_ns INTEGER NOT NULL,boot_id TEXT NOT NULL,mode TEXT NOT NULL,
              host_json TEXT NOT NULL,services_json TEXT NOT NULL,process_blob BLOB NOT NULL,
              processes_seen INTEGER NOT NULL,processes_permission_denied INTEGER NOT NULL,
              processes_exited INTEGER NOT NULL,errors_json TEXT NOT NULL,duration_ns INTEGER NOT NULL,
              capture_reason TEXT);
            CREATE TABLE events(id INTEGER PRIMARY KEY,sampled_at_ns INTEGER NOT NULL,
              kind TEXT NOT NULL,severity TEXT NOT NULL,entity TEXT,details_json TEXT NOT NULL);
            CREATE TABLE host_rollups(bucket_start_ns INTEGER PRIMARY KEY,sample_count INTEGER NOT NULL,
              values_json TEXT NOT NULL,coverage_json TEXT NOT NULL);
        """)
        process = {"pid": 12, "start_ticks": 4, "name": "worker", "user": "owner",
                   "service": "api", "rss_bytes": 128}
        conn.execute("INSERT INTO samples(sampled_at_ns,monotonic_ns,boot_id,mode,host_json,"
                     "services_json,process_blob,processes_seen,processes_permission_denied,"
                     "processes_exited,errors_json,duration_ns,capture_reason) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (now - 2_000_000_000, now - 2_000_000_000, "boot-a", "baseline",
                      json.dumps({"cpu_busy_pct": 25}), "{}", gzip.compress(json.dumps([process]).encode()),
                      1, 0, 0, "[]", 1000, None))
        conn.execute("INSERT INTO events(sampled_at_ns,kind,severity,entity,details_json) VALUES(?,?,?,?,?)",
                     (now - 2_000_000_000, "sample", "info", "host", "{}"))


def test_monitor_queries_use_system_python_with_broken_backend(installed):
    _, link, state, env = installed
    _store(state)
    commands = (
        (("status",), "host"),
        (("series", "cpu_busy_pct", "--since", "1m", "--step", "5"), "value"),
        (("processes", "--name", "worker"), "process"),
        (("events", "--kind", "sample"), "kind"),
    )
    for args, item_key in commands:
        result = _run(link, env, "monitor", *args)
        assert result.returncode == 0, result.stderr or result.stdout
        payload = json.loads(result.stdout)
        assert payload["schema"] == 1
        assert payload["items"] and item_key in payload["items"][0]
        assert len(result.stdout.encode()) <= 4097  # the one extra byte is the line ending

    small = _run(link, env, "monitor", "status", "--max-bytes", "512")
    assert small.returncode == 0
    assert len(small.stdout.encode()) <= 513
    assert json.loads(small.stdout)["schema"] == 1


def test_installed_process_tree_flag_reaches_standalone_reader(installed):
    _, link, state, env = installed
    _store(state)
    result = _run(link, env, "monitor", "processes", "--view", "tree", "--limit", "1")
    assert result.returncode == 0, result.stderr or result.stdout
    payload = json.loads(result.stdout)
    assert payload["requested"]["view"] == "tree"
    assert payload["coverage"]["tree"]["scope"] == "stored_observation"
    assert payload["items"][0]["tree"]["depth"] == 0


def test_installed_gpu_query_and_series_share_retained_observation(installed):
    _, link, state, env = installed
    _store(state)
    with sqlite3.connect(state / "monitor.sqlite3") as conn:
        sampled = conn.execute("SELECT sampled_at_ns FROM samples").fetchone()[0]
        gpu = {"provider": "nvidia-smi", "availability": "ok",
               "observed_at_ns": sampled - 1_000_000_000,
               "poll_interval_seconds": 15, "device_identity_scope": "sample_boot_id+index",
               "devices_seen": 1, "devices_scanned": 1, "missing_fields": {},
               "max_utilization_pct": 32, "memory_used_bytes": 100, "memory_total_bytes": 1000,
               "devices": [{"index": 0, "name": "GPU A", "utilization_pct": 32,
                            "memory_used_bytes": 100, "memory_total_bytes": 1000,
                            "temperature_c": 40, "power_w": 50}]}
        conn.execute("UPDATE samples SET host_json=?", (json.dumps({"gpu": gpu,
                     "gpu_max_utilization_pct": 32}),))
    snapshot = _run(link, env, "monitor", "gpu")
    assert snapshot.returncode == 0, snapshot.stderr or snapshot.stdout
    payload = json.loads(snapshot.stdout)
    assert payload["coverage"]["provider"] == "nvidia-smi"
    assert payload["items"][0]["device"]["name"] == "GPU A"
    start = datetime.fromtimestamp((sampled - 10_000_000_000) / 1_000_000_000, UTC).isoformat()
    end = datetime.fromtimestamp((sampled + 10_000_000_000) / 1_000_000_000, UTC).isoformat()
    series = _run(link, env, "monitor", "series", "gpu_utilization_pct", "--entity", "gpu:0",
                  "--boot-id", payload["coverage"]["boot_id"], "--since", start,
                  "--until", end, "--step", "5")
    assert series.returncode == 0, series.stderr or series.stdout
    assert any(item["value"] and item["value"]["last"] == 32
               for item in json.loads(series.stdout)["items"])


def test_monitor_failures_stay_structured_without_store(installed):
    _, link, _, env = installed
    result = _run(link, env, "monitor", "status")
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["coverage"]["availability"] == "collector_stopped"
    assert payload["errors"][0]["code"] == "collector_stopped"

    result = _run(link, env, "monitor", "events", "--since", "1m", "--until", "2026-09-26T12:00:00Z",
                  "--cursor", "abc")
    assert result.returncode == 1
    assert json.loads(result.stdout)["errors"][0]["message"].startswith("pagination requires")

    result = _run(link, env, "monitor", "events", "--since", "not-a-time")
    assert result.returncode == 1
    assert json.loads(result.stdout)["errors"][0]["message"] == "invalid UTC time"


def test_on_demand_commands_use_standalone_dispatch(installed, tmp_path: Path):
    _, link, state, env = installed
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    commands = {
        "journalctl": ("import json,time\nprint(json.dumps({\"__REALTIME_TIMESTAMP\": str((time.time_ns()-1_000_000_000)//1000), "
                       "\"__CURSOR\": \"s=1\", \"MESSAGE\": \"token=abc\", \"PRIORITY\": \"6\"}))\n"),
        "systemctl": "print('summitflow-backend.service enabled')\n",
        "dpkg-query": "print('sample-package\\t1.0')\n",
    }
    for name, body in commands.items():
        path = fake_bin / name
        path.write_text("#!/usr/bin/python3\n" + body)
        path.chmod(0o755)
    env = {**env, "PATH": str(fake_bin) + os.pathsep + env["PATH"]}

    cases = (
        (("logs", "backend", "--since", "1m", "--priority", "6"), "logs"),
        (("sensors", "--limit", "2"), "sensors"),
        (("connections", "--show-addresses", "--include-process", "--limit", "2"), "connections"),
        (("system-info",), "system_info"),
        (("users", "--limit", "2"), "users"),
        (("startup", "--limit", "2"), "startup"),
        (("apps", "--limit", "2"), "apps"),
        (("drivers", "--limit", "2"), "drivers"),
    )
    with _observations(state, 4) as received:
        for args, kind in cases:
            result = _run(link, env, "monitor", *args)
            assert result.returncode == 0, (args, result.stderr, result.stdout)
            payload = json.loads(result.stdout)
            assert payload["schema"] == 1
            assert payload["requested"]["kind"] == kind
            assert len(result.stdout.encode()) <= 4097
            if kind == "logs":
                assert payload["requested"]["priority"] == 6
            if kind == "connections":
                assert payload["requested"]["include_addresses"] is True
                assert payload["requested"]["include_process"] is True
        log = json.loads(_run(link, env, "monitor", "logs", "backend", "--since", "1m").stdout)
        assert log["items"][0]["value"]["message"] == "token=[REDACTED]"
        assert log["requested"]["since"].endswith("+00:00")
        connections = json.loads(_run(link, env, "monitor", "connections", "--show-addresses").stdout)
        assert connections["requested"]["include_addresses"] is True
    assert [row["source"] for row in received] == ["logs", "connections", "logs", "connections"]


def test_on_demand_failures_stay_structured(installed):
    _, link, _, env = installed
    result = _run(link, env, "monitor", "logs", "other-service")
    assert result.returncode == 1
    assert json.loads(result.stdout)["errors"][0]["message"] == "collector observation unavailable"
    result = _run(link, env, "monitor", "logs", "backend", "--since", "1m",
                  "--until", "2026-09-26T12:00:00Z", "--cursor", "s=1")
    assert result.returncode == 1
    assert json.loads(result.stdout)["errors"][0]["message"].startswith("pagination requires")


def test_extended_commands_use_standalone_dispatch(installed, tmp_path: Path):
    root, link, state, env = installed
    _store(state)
    scan = root / "scan-fixture"
    scan.mkdir()
    (scan / "visible.txt").write_bytes(b"12345")
    (scan / ".hidden").write_bytes(b"hidden")

    with _observations(state, 1) as received:
        disk = _run(link, env, "monitor", "disk-space", str(scan), "--max-depth", "1",
                    "--max-entries", "20")
    assert disk.returncode == 0, disk.stderr or disk.stdout
    disk_payload = json.loads(disk.stdout)
    assert disk_payload["requested"]["kind"] == "disk_space"
    assert disk_payload["items"][0]["value"]["name"] == "visible.txt"
    assert disk_payload["coverage"]["complete"] is False
    assert len(disk.stdout.encode()) <= 4097
    assert received[0]["params"]["path"] == str(scan)

    cpu = _run(link, env, "monitor", "benchmark", "cpu", "--duration-seconds", "0.01")
    assert cpu.returncode == 0, cpu.stderr or cpu.stdout
    cpu_payload = json.loads(cpu.stdout)
    assert cpu_payload["requested"]["kind"] == "benchmark"
    assert cpu_payload["items"][0]["value"]["bytes_processed"] > 0
    assert len(cpu.stdout.encode()) <= 4097

    unsupported = _run(link, env, "monitor", "benchmark", "network")
    assert unsupported.returncode == 0
    assert json.loads(unsupported.stdout)["coverage"]["availability"] == "unsupported"

    start = "2020-01-01T00:00:00Z"
    end = "2030-01-01T00:00:00Z"
    exported = _run(link, env, "monitor", "export", "--since", start, "--until", end)
    assert exported.returncode == 1  # window beyond the documented one-day cap
    assert json.loads(exported.stdout)["errors"][0]["code"] == "query_error"
    now = datetime.now(UTC)
    start = (now - timedelta(minutes=1)).isoformat()
    end = now.isoformat()
    exported = _run(link, env, "monitor", "export", "--since", start, "--until", end)
    assert exported.returncode == 0, exported.stderr or exported.stdout
    replay = json.loads(exported.stdout)
    assert replay["requested"]["kind"] == "capture_export"
    assert {row["type"] for row in replay["items"]} == {"sample", "event"}
    assert "worker" not in exported.stdout
    assert len(exported.stdout.encode()) <= 4097
    page = _run(link, env, "monitor", "export", "--since", start, "--until", end,
                "--limit", "1")
    first = json.loads(page.stdout)
    assert page.returncode == 0 and first["truncated"] and first["next_cursor"]
    next_page = _run(link, env, "monitor", "export", "--since", start, "--until", end,
                     "--limit", "1", "--cursor", first["next_cursor"])
    assert next_page.returncode == 0
    assert json.loads(next_page.stdout)["items"][0]["type"] != first["items"][0]["type"]


def test_extended_command_failures_are_structured(installed, tmp_path: Path):
    _, link, _state, env = installed
    outside = tmp_path / "outside"
    outside.mkdir()
    denied = _run(link, env, "monitor", "disk-space", str(outside))
    assert denied.returncode == 1
    assert json.loads(denied.stdout)["errors"][0]["code"] == "query_error"
    invalid = _run(link, env, "monitor", "export", "--since", "1m", "--until",
                   "2026-09-26T12:00:00Z", "--cursor", "abc")
    assert invalid.returncode == 1
    assert json.loads(invalid.stdout)["errors"][0]["message"].startswith("pagination requires")
    missing = _run(link, env, "monitor", "export", "--since", "2026-09-26T11:00:00Z",
                   "--until", "2026-09-26T12:00:00Z")
    assert missing.returncode == 1
    assert json.loads(missing.stdout)["coverage"]["availability"] == "collector_stopped"


@pytest.mark.parametrize(("args", "expected"), [
    (("capture", "--ttl-seconds", "10"), {"command": "lease_start", "ttl_seconds": 10}),
    (("capture-renew", "a" * 32, "--ttl-seconds", "10"),
     {"command": "lease_renew", "lease_id": "a" * 32, "ttl_seconds": 10}),
    (("capture-end", "a" * 32), {"command": "lease_end", "lease_id": "a" * 32}),
])
def test_monitor_capture_control_with_broken_backend(installed, args, expected):
    _, link, state, env = installed
    path = state / "control.sock"
    received = []
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(str(path))
        server.listen(1)

        def serve() -> None:
            connection, _ = server.accept()
            with connection:
                with connection.makefile("rb") as stream:
                    received.append(json.loads(stream.readline()))
                connection.sendall(b'{"ok":true,"lease_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}\n')

        worker = threading.Thread(target=serve, daemon=True)
        worker.start()
        result = _run(link, env, "monitor", *args)
        worker.join(timeout=2)
    assert result.returncode == 0, result.stderr or result.stdout
    assert received == [expected]
    assert json.loads(result.stdout)["ok"] is True

    for command in ("capture-renew", "capture-end"):
        result = _run(link, env, "monitor", command, "bad-id")
        assert result.returncode == 1
        assert json.loads(result.stdout)["errors"][0]["message"] == "invalid lease id"


def test_other_commands_exec_original_entry_point_with_exact_arguments(installed):
    root, link, _, env = installed
    entry = root / "backend" / ".venv" / "bin" / "st"
    entry.parent.mkdir(parents=True)
    entry.write_text("#!/usr/bin/python3\nimport json, sys\nprint(json.dumps(sys.argv[1:]))\nsys.exit(23)\n")
    entry.chmod(0o755)
    (entry.parent / "python").symlink_to(sys.executable)
    result = _run(link, env, "service", "status", "a b", "")
    assert result.returncode == 23
    assert json.loads(result.stdout) == ["service", "status", "a b", ""]


def test_rejected_capture_is_a_structured_failure(installed):
    _, link, state, env = installed
    path = state / "control.sock"
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(str(path))
        server.listen(1)

        def serve() -> None:
            connection, _ = server.accept()
            with connection:
                with connection.makefile("rb") as stream:
                    stream.readline()
                connection.sendall(b'{"ok":false,"error":"unknown_or_expired_lease"}\n')

        worker = threading.Thread(target=serve, daemon=True)
        worker.start()
        result = _run(link, env, "monitor", "capture-end", "a" * 32)
        worker.join(timeout=2)
    assert result.returncode == 1
    assert json.loads(result.stdout)["errors"][0]["message"] == "unknown_or_expired_lease"
