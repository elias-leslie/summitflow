"""Fixture-backed checks of the standalone SQLite monitor reader."""

import fcntl
import gzip
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from monitor_reader import (
    MonitorQueryError,
    MonitorReader,
    MonitorSchemaError,
    encode_budgeted_json,
)

NSEC = 1_000_000_000
NOW = int(datetime(2026, 9, 26, 12, tzinfo=UTC).timestamp() * NSEC)


def test_maintenance_lock_blocks_new_reader_without_touching_history(store):
    directory, conn = store
    _sample(conn, when=NOW - NSEC)
    conn.commit()
    lock_path = directory / "maintenance.lock"
    assert MonitorReader(directory).status(now=NOW)["coverage"]["sample_count"] == 1
    with lock_path.open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(MonitorQueryError, match="maintenance in progress"):
            MonitorReader(directory).status(now=NOW)
    assert MonitorReader(directory).status(now=NOW)["coverage"]["sample_count"] == 1
    assert lock_path.stat().st_mode & 0o777 == 0o600


def test_surviving_migration_interlock_blocks_reader_after_lock_released(store):
    directory, conn = store
    _sample(conn, when=NOW - NSEC)
    conn.commit()
    reader = MonitorReader(directory)
    assert reader.status(now=NOW)["coverage"]["sample_count"] == 1
    marker = directory / "migration.interlock"
    marker.write_text("recovery receipt\n")
    with pytest.raises(MonitorQueryError, match="maintenance recovery required"):
        reader.status(now=NOW)
    marker.unlink()
    assert reader.status(now=NOW)["coverage"]["sample_count"] == 1


def _sample(conn, *, when, mono=None, mode="baseline", host=None, services=None, processes=None,
            errors=None, denied=0, boot="boot-a"):
    host = host if host is not None else {"cpu_busy_pct": 0, "memory_available_bytes": 100}
    processes = processes if processes is not None else []
    conn.execute(
        "INSERT INTO samples(sampled_at_ns,monotonic_ns,boot_id,mode,host_json,services_json,"
        "process_blob,processes_seen,processes_permission_denied,processes_exited,errors_json,"
        "duration_ns,capture_reason) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (when, mono if mono is not None else when, boot, mode, json.dumps(host), json.dumps(services or {}), gzip.compress(json.dumps(processes).encode()),
         len(processes) + denied, denied, 0, json.dumps(errors or []), 1000, None),
    )


def _host_counters(kind: str, members: dict[str, list[int | str]]) -> dict:
    source = f"{kind}:{json.dumps(sorted(members), separators=(',', ':'))}"
    if kind == "net":
        return {"net_source": source, "net_members": members,
                "net_rx_bytes": sum(member[0] for member in members.values()),
                "net_tx_bytes": sum(member[1] for member in members.values())}
    return {"disk_source": source, "disk_members": members,
            "disk_read_bytes": sum(member[0] for member in members.values()),
            "disk_write_bytes": sum(member[1] for member in members.values())}


@pytest.fixture
def store(tmp_path: Path):
    path = tmp_path / "monitor.sqlite3"
    conn = sqlite3.connect(path)
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
        CREATE INDEX samples_time ON samples(sampled_at_ns,id);
        CREATE TABLE events(id INTEGER PRIMARY KEY,sampled_at_ns INTEGER NOT NULL,
          kind TEXT NOT NULL,severity TEXT NOT NULL,entity TEXT,details_json TEXT NOT NULL);
        CREATE INDEX events_time ON events(sampled_at_ns,id);
        CREATE TABLE host_rollups(bucket_start_ns INTEGER PRIMARY KEY,sample_count INTEGER NOT NULL,
          values_json TEXT NOT NULL,coverage_json TEXT NOT NULL);
    """)
    yield tmp_path, conn
    conn.close()


def test_status_and_series_preserve_zero_denial_and_gap(store):
    directory, conn = store
    _sample(conn, when=NOW - 20 * NSEC, host={"cpu_busy_pct": 0})
    _sample(conn, when=NOW - 10 * NSEC, host={"cpu_busy_pct": None, "process_io_permission_denied": 3},
            errors=[{"source": "/proc/stat", "code": "permission_denied"}], denied=2)
    conn.commit()
    reader = MonitorReader(directory)
    status = reader.status(now=NOW)
    assert status["coverage"]["availability"] == "ok"
    assert status["coverage"]["processes_permission_denied"] == 2
    assert status["coverage"]["process_io_permission_denied"] == 3
    assert status["items"][0]["host"]["cpu_busy_pct"] is None
    result = reader.series("cpu_busy_pct", since=NOW - 30 * NSEC, until=NOW,
                           step=10, limit=10, now=NOW)
    assert [item["value"]["last"] if item["value"] else None for item in result["items"]] == [None, 0, None]
    assert result["items"][0]["coverage"]["missing"] > 0
    assert result["items"][2]["availability"] == "permission_denied"
    assert result["items"][2]["last_sampled_at"] == datetime.fromtimestamp((NOW - 10 * NSEC) / NSEC, UTC).isoformat().replace("+00:00", ".000000000Z")
    assert result["items"][2]["coverage"]["unavailable"] == {"permission_denied": 1}
    assert len(encode_budgeted_json(result)) <= 4096


def test_status_stale_and_backend_independent_read(store):
    directory, conn = store
    _sample(conn, when=NOW - 100 * NSEC)
    conn.commit()
    conn.close()  # No collector or backend process is required for a committed read.
    status = MonitorReader(directory).status(now=NOW)
    assert status["coverage"]["availability"] == "stale"
    assert status["items"][0]["freshness"] == "stale"


def test_detail_status_uses_persisted_five_second_cadence(store):
    directory, conn = store
    _sample(conn, when=NOW - 9 * NSEC, mode="detail")
    conn.commit()
    assert MonitorReader(directory).status(now=NOW)["coverage"]["availability"] == "ok"


def test_service_series_reads_metrics_object(store):
    directory, conn = store
    _sample(conn, when=NOW - 5 * NSEC,
            services={"summitflow-backend": {"active_state": "active", "metrics": {
                "source": "cgroup2", "memory_current_bytes": 1234}}})
    conn.commit()
    series = MonitorReader(directory).series("memory_current_bytes", entity="summitflow-backend",
                                             since=NOW - 5 * NSEC, until=NOW,
                                             step=5, now=NOW)
    assert series["items"][0]["value"]["last"] == 1234
    assert series["items"][0]["unit"] == "bytes"


def test_service_derived_rates_skip_cache_and_use_monotonic_interval(store):
    directory, conn = store
    def service(observed, cpu, read, write):
        return {"api": {"observed_at_ns": observed, "metrics": {
            "source": "cgroup2", "cpu_usage_usec": cpu,
            "io_read_bytes": read, "io_write_bytes": write}}}
    first = service(NOW - 20 * NSEC, 100_000, 100, 50)
    second = service(NOW - 10 * NSEC, 250_000, 600, 150)
    _sample(conn, when=NOW - 20 * NSEC, mono=10 * NSEC, services=first)
    _sample(conn, when=NOW - 15 * NSEC, mono=15 * NSEC, services=first, mode="detail")
    _sample(conn, when=NOW - 10 * NSEC, mono=20 * NSEC, services=second)
    _sample(conn, when=NOW - 5 * NSEC, mono=25 * NSEC, services=second, mode="detail")
    conn.commit()
    reader = MonitorReader(directory)
    cpu = reader.series("cpu_percent", entity="api", since=NOW - 20 * NSEC,
                        until=NOW, step=5, now=NOW)
    assert [item["value"]["last"] if item["value"] else None for item in cpu["items"]] == [None, None, 1.5, None]
    assert cpu["items"][2]["unit"] == "%"
    assert cpu["items"][1]["availability"] == "not_collected"
    read = reader.series("io_read_bytes_per_second", entity="api", since=NOW - 10 * NSEC,
                         until=NOW, step=5, now=NOW)
    write = reader.series("io_write_bytes_per_second", entity="api", since=NOW - 10 * NSEC,
                          until=NOW, step=5, now=NOW)
    assert read["items"][0]["value"]["last"] == 50
    assert write["items"][0]["value"]["last"] == 10
    assert read["items"][0]["unit"] == "bytes/s"


def test_service_rate_rejects_cross_boot_source_change_and_missing_counter(store):
    directory, conn = store
    def service(at, cpu, source="cgroup2"):
        return {"api": {"observed_at_ns": at, "metrics": {
            "source": source, "cpu_usage_usec": cpu}}}
    _sample(conn, when=NOW - 20 * NSEC, mono=10 * NSEC,
            services=service(NOW - 20 * NSEC, 10))
    _sample(conn, when=NOW - 15 * NSEC, mono=15 * NSEC, boot="boot-b",
            services=service(NOW - 15 * NSEC, 20))
    _sample(conn, when=NOW - 10 * NSEC, mono=20 * NSEC, boot="boot-b",
            services=service(NOW - 10 * NSEC, 30, "main_pid_fallback"))
    _sample(conn, when=NOW - 5 * NSEC, mono=25 * NSEC, boot="boot-b",
            services=service(NOW - 5 * NSEC, None, "main_pid_fallback"))
    conn.commit()
    result = MonitorReader(directory).series("cpu_percent", entity="api",
                                             since=NOW - 20 * NSEC, until=NOW,
                                             step=5, now=NOW)
    assert all(item["value"] is None for item in result["items"])
    assert all(item["coverage"]["valid"] == 0 for item in result["items"])


def test_main_pid_rate_uses_process_scan_interval_and_ignores_cached_counter(store):
    directory, conn = store
    def fallback(sample_at, scan_at, scan_mono, counter):
        return {"api": {"observed_at_ns": sample_at, "metrics": {
            "source": "main_pid_fallback", "pid": 7, "start_ticks": 99,
            "cpu_usage_usec": counter, "observed_at_ns": scan_at,
            "observed_monotonic_ns": scan_mono}}}
    for seconds_ago, scan_seconds_ago, counter in ((20, 20, 100_000), (15, 20, 100_000),
                                                   (10, 20, 100_000), (5, 5, 250_000)):
        at = NOW - seconds_ago * NSEC
        scan_at = NOW - scan_seconds_ago * NSEC
        _sample(conn, when=at, mono=(30 - seconds_ago) * NSEC,
                services=fallback(at, scan_at, (30 - scan_seconds_ago) * NSEC, counter))
    conn.commit()
    result = MonitorReader(directory).series("cpu_percent", entity="api",
                                             since=NOW - 20 * NSEC, until=NOW,
                                             step=5, now=NOW)
    assert [item["value"]["last"] if item["value"] else None for item in result["items"]] == [None, None, None, 1.0]


def test_host_series_counts_baseline_once_when_detail_row_shares_timestamp(store):
    directory, conn = store
    at = NOW - 5 * NSEC
    _sample(conn, when=at, host={"cpu_busy_pct": 10})
    _sample(conn, when=at, mode="detail", host={"cpu_busy_pct": 10})
    conn.commit()
    result = MonitorReader(directory).series("cpu_busy_pct", since=at, until=NOW, step=5, now=NOW)
    assert result["items"][0]["coverage"] == {
        "expected": 1, "observed": 1, "valid": 1, "missing": 0, "unavailable": {}}


def test_host_throughput_uses_monotonic_interval_and_previous_page_sample(store):
    directory, conn = store
    first = {**_host_counters("disk", {"sda": [100, 200, "8:0"]}),
             **_host_counters("net", {"eth0": [300, 400, "2"]})}
    second = {**_host_counters("disk", {"sda": [600, 400, "8:0"]}),
              **_host_counters("net", {"eth0": [1_300, 2_400, "2"]})}
    _sample(conn, when=NOW - 10 * NSEC, mono=10 * NSEC, host=first)
    _sample(conn, when=NOW - 5 * NSEC, mono=20 * NSEC, host=second)
    _sample(conn, when=NOW - 5 * NSEC, mono=20 * NSEC, mode="detail", host=second)
    conn.commit()
    reader = MonitorReader(directory)
    for metric, rate in (("disk_read_bytes_per_second", 50),
                         ("disk_write_bytes_per_second", 20),
                         ("net_rx_bytes_per_second", 100),
                         ("net_tx_bytes_per_second", 200)):
        result = reader.series(metric, since=NOW - 5 * NSEC, until=NOW,
                               step=5, now=NOW)
        assert result["items"][0]["value"]["last"] == rate
        assert result["items"][0]["coverage"]["valid"] == 1
        assert result["items"][0]["unit"] == "bytes/s"


def test_host_throughput_reports_gaps_for_reset_boot_source_and_interval(store):
    directory, conn = store
    records = (
        (30, 10, "boot-a", 100, "net:[\"eth0\"]"),
        (25, 15, "boot-a", 150, "net:[\"eth0\"]"),
        (20, 20, "boot-a", 30, "net:[\"eth0\"]"),  # Counter reset.
        (15, 25, "boot-b", 80, "net:[\"eth0\"]"),
        (10, 30, "boot-b", 100, "other-provider"),
        (5, 50, "boot-b", 200, "other-provider"),  # Interval exceeds 15s.
    )
    for ago, mono, boot, counter, source in records:
        _sample(conn, when=NOW - ago * NSEC, mono=mono * NSEC, boot=boot,
                host={**_host_counters("net", {"eth0": [counter, 0, "2"]}),
                      "net_source": source})
    conn.commit()
    result = MonitorReader(directory).series("net_rx_bytes_per_second",
                                             since=NOW - 30 * NSEC, until=NOW,
                                             step=5, now=NOW)
    assert [item["value"]["last"] if item["value"] else None for item in result["items"]] == [None, 10, None, None, None, None]
    assert result["items"][2]["coverage"]["unavailable"] == {"not_collected": 1}


def test_host_throughput_rejects_masked_member_reset_and_recreation(store):
    directory, conn = store
    samples = (
        (20, {"eth0": [100, 10, "2"], "eth1": [100, 20, "3"]}),
        (15, {"eth0": [90, 11, "2"], "eth1": [300, 30, "3"]}),
        (10, {"eth0": [110, 12, "4"], "eth1": [320, 31, "3"]}),
        (5, {"eth0": [130, 13, "4"], "eth1": [340, 32, "3"]}),
    )
    for ago, members in samples:
        _sample(conn, when=NOW - ago * NSEC, mono=(30 - ago) * NSEC,
                host=_host_counters("net", members))
    conn.commit()
    result = MonitorReader(directory).series("net_rx_bytes_per_second",
                                             since=NOW - 20 * NSEC, until=NOW,
                                             step=5, now=NOW)
    assert [item["value"]["last"] if item["value"] else None for item in result["items"]] == [None, None, None, 8]
    assert result["items"][1]["coverage"]["unavailable"] == {"not_collected": 1}


def test_host_throughput_requires_member_evidence_and_invalid_last_is_gap(store):
    directory, conn = store
    _sample(conn, when=NOW - 20 * NSEC, mono=10 * NSEC,
            host={"net_rx_bytes": 100, "net_source": "net:[\"eth0\"]"})
    _sample(conn, when=NOW - 15 * NSEC, mono=15 * NSEC,
            host=_host_counters("net", {"eth0": [150, 0, "2"]}))
    _sample(conn, when=NOW - 10 * NSEC, mono=20 * NSEC,
            host=_host_counters("net", {"eth0": [200, 0, "2"]}))
    _sample(conn, when=NOW - 5 * NSEC, mono=25 * NSEC,
            host=_host_counters("net", {"eth0": [10, 0, "2"]}))
    conn.commit()
    result = MonitorReader(directory).series("net_rx_bytes_per_second",
                                             since=NOW - 20 * NSEC, until=NOW,
                                             step=10, now=NOW)
    assert result["items"][0]["value"] is None
    assert result["items"][1]["value"] is None  # Last sample reset despite earlier valid rate.
    assert result["items"][1]["coverage"]["valid"] == 1
    assert result["items"][1]["availability"] == "not_collected"
    status = MonitorReader(directory).status(now=NOW)
    assert "net_members" not in status["items"][0]["host"]


def test_historical_host_throughput_rejects_counter_rollups(store):
    directory, conn = store
    conn.commit()
    with pytest.raises(MonitorQueryError, match="rollup counters cannot provide a valid rate"):
        MonitorReader(directory).series("disk_read_bytes_per_second",
                                        since=NOW - 2 * 24 * 60 * 60 * NSEC,
                                        until=NOW, step=60, now=NOW)


def test_historical_host_series_uses_rollups_and_reports_gaps(store):
    directory, conn = store
    start = NOW - 3 * 24 * 60 * 60 * NSEC
    minute = 60 * NSEC
    for index in (0, 1, 3):
        conn.execute("INSERT INTO host_rollups VALUES(?,?,?,?)",
                     (start + index * minute, 12,
                      json.dumps({"cpu_busy_pct": {"min": index, "max": index + 2,
                                                   "mean": index + 1, "last": index + 2,
                                                   "valid_count": 11}}),
                      json.dumps({"cpu_busy_pct_unavailable_count": 1, "gap_count": 0})))
    conn.commit()
    series = MonitorReader(directory).series("cpu_busy_pct", since=start, until=NOW,
                                             step=60, limit=10, now=NOW)
    assert len(series["items"]) >= 4
    assert series["items"][0]["value"]["mean"] == 1
    assert series["items"][0]["coverage"]["unavailable"] == {"not_collected": 1}
    assert series["items"][2]["value"] is None
    assert series["items"][2]["coverage"]["missing"] == 12
    assert series["coverage"]["resolution_seconds"] == 60


def test_sparse_gpu_series_uses_poll_time_and_preserves_provider_outcomes(store):
    directory, conn = store
    devices = [
        {"index": 0, "name": "GPU A", "utilization_pct": 50, "memory_used_bytes": 10,
         "memory_total_bytes": 100, "temperature_c": 40, "power_w": 75},
        {"index": 1, "name": "GPU B", "utilization_pct": 25, "memory_used_bytes": 20,
         "memory_total_bytes": 100, "temperature_c": 45, "power_w": 80},
    ]
    first = {"provider": "nvidia-smi", "availability": "ok", "observed_at_ns": NOW - 47 * NSEC,
             "poll_interval_seconds": 15, "device_identity_scope": "sample_boot_id+index",
             "devices_seen": 2, "devices_scanned": 2, "devices": devices, "missing_fields": {},
             "max_utilization_pct": 50, "memory_used_bytes": 30, "memory_total_bytes": 200}
    second = {**first, "availability": "partial", "observed_at_ns": NOW - 32 * NSEC,
              "devices": [{**devices[0], "utilization_pct": None}, devices[1]],
              "max_utilization_pct": None, "missing_fields": {"utilization_pct": 1}}
    _sample(conn, when=NOW - 45 * NSEC, host={"gpu": first, "gpu_max_utilization_pct": 50})
    _sample(conn, when=NOW - 40 * NSEC, host={"cpu_busy_pct": 9})
    _sample(conn, when=NOW - 30 * NSEC, host={"gpu": second, "gpu_max_utilization_pct": None},
            errors=[{"source": "nvidia-smi", "code": "field_unavailable"}])
    conn.commit()
    reader = MonitorReader(directory)
    aggregate = reader.series("gpu_max_utilization_pct", since=NOW - 60 * NSEC,
                              until=NOW, step=15, now=NOW)
    assert aggregate["items"][0]["value"]["last"] == 50
    assert aggregate["items"][0]["observed_at"] == reader.gpu(at=NOW - 45 * NSEC, now=NOW)["coverage"]["observed_at"]
    assert aggregate["items"][1]["value"] is None
    assert aggregate["items"][1]["availability"] == "partial"
    assert aggregate["items"][1]["provider_availability"] == "partial"
    assert aggregate["items"][1]["coverage"]["observed"] == 1
    assert aggregate["items"][2]["value"] is None
    assert aggregate["items"][2]["coverage"]["missing"] == 1
    with pytest.raises(MonitorQueryError, match="boot_id"):
        reader.series("gpu_utilization_pct", entity="gpu:0", since=NOW - 60 * NSEC,
                      until=NOW, step=15, now=NOW)
    device = reader.series("gpu_utilization_pct", entity="gpu:0", boot_id="boot-a",
                           since=NOW - 60 * NSEC, until=NOW, step=15, now=NOW)
    assert device["items"][0]["value"]["last"] == 50
    assert device["items"][1]["value"] is None
    assert device["items"][1]["availability"] == "partial"
    assert device["items"][1]["coverage"]["unavailable"] == {"partial": 1}
    assert device["items"][0]["device_identity_scope"] == "sample_boot_id+index"
    snapshot = reader.gpu(now=NOW, limit=1)
    assert snapshot["coverage"]["availability"] == "partial"
    assert snapshot["coverage"]["freshness"] == "stale"
    assert snapshot["coverage"]["source_errors"] == ["field_unavailable"]
    assert snapshot["items"][0]["device"]["name"] == "GPU A"
    next_page = reader.gpu(now=NOW, limit=1, cursor=snapshot["next_cursor"])
    assert next_page["items"][0]["device"]["name"] == "GPU B"
    assert next_page["coverage"]["sample_id"] == snapshot["coverage"]["sample_id"]
    status = reader.status(now=NOW)
    assert "gpu" not in status["items"][0]["host"]
    assert status["items"][0]["host"]["gpu_max_utilization_pct"] is None


def test_gpu_latest_distinguishes_disabled_and_retention(store):
    directory, conn = store
    gpu = {"provider": "nvidia-smi", "availability": "disabled", "observed_at_ns": NOW,
           "poll_interval_seconds": None, "status_refresh_seconds": 3600,
           "device_identity_scope": "sample_boot_id+index",
           "devices_seen": 0, "devices_scanned": 0, "devices": [], "missing_fields": {},
           "max_utilization_pct": None, "memory_used_bytes": None, "memory_total_bytes": None}
    _sample(conn, when=NOW, host={"gpu": gpu})
    conn.commit()
    result = MonitorReader(directory).gpu(now=NOW)
    assert result["items"] == []
    assert result["coverage"]["availability"] == "disabled"
    assert result["coverage"]["freshness"] == "ok"
    assert result["coverage"]["status_refresh_seconds"] == 3600
    assert MonitorReader(directory).gpu(now=NOW + 1800 * NSEC)["coverage"]["freshness"] == "ok"
    assert MonitorReader(directory).gpu(now=NOW + 3700 * NSEC)["coverage"]["freshness"] == "stale"
    expired = MonitorReader(directory).gpu(now=NOW + 2 * 24 * 60 * 60 * NSEC)
    assert expired["coverage"]["availability"] == "not_collected"


def test_gpu_device_history_never_joins_same_index_across_boots(store):
    directory, conn = store
    for ago, boot, value in ((30, "boot-a", 10), (15, "boot-b", 90)):
        gpu = {"provider": "nvidia-smi", "availability": "ok",
               "observed_at_ns": NOW - (ago + 2) * NSEC,
               "devices": [{"index": 0, "name": "GPU", "utilization_pct": value}],
               "max_utilization_pct": value}
        _sample(conn, when=NOW - ago * NSEC, host={"gpu": gpu}, boot=boot)
    conn.commit()
    reader = MonitorReader(directory)
    aggregate = reader.series("gpu_max_utilization_pct", since=NOW - 45 * NSEC,
                              until=NOW, step=15, now=NOW)
    assert [item["value"]["last"] if item["value"] else None for item in aggregate["items"]] == [10, 90, None]
    scoped = reader.series("gpu_utilization_pct", entity="gpu:0", boot_id="boot-a",
                           since=NOW - 45 * NSEC, until=NOW, step=15, now=NOW)
    assert [item["value"]["last"] if item["value"] else None for item in scoped["items"]] == [10, None, None]
    with pytest.raises(MonitorQueryError, match="retained raw observations"):
        reader.series("gpu_max_utilization_pct", since=NOW - 2 * 24 * 60 * 60 * NSEC,
                      until=NOW, step=60, now=NOW)


def test_gpu_device_page_rejects_reused_sample_id(store):
    directory, conn = store
    gpu = {"provider": "nvidia-smi", "availability": "ok", "observed_at_ns": NOW,
           "devices": [{"index": 0, "name": "A"}, {"index": 1, "name": "B"}]}
    _sample(conn, when=NOW, host={"gpu": gpu})
    conn.commit()
    reader = MonitorReader(directory)
    first = reader.gpu(limit=1, now=NOW)
    old_id = first["coverage"]["sample_id"]
    assert first["next_cursor"]
    conn.execute("DELETE FROM samples")
    _sample(conn, when=NOW + NSEC, host={"gpu": {**gpu, "observed_at_ns": NOW + NSEC}}, boot="boot-b")
    conn.commit()
    assert conn.execute("SELECT id FROM samples").fetchone()[0] == old_id
    resumed = reader.gpu(limit=1, cursor=first["next_cursor"], now=NOW + NSEC)
    assert resumed["items"] == []
    assert resumed["coverage"]["availability"] == "retention_expired"


def test_historical_gpu_page_reads_only_its_bucket_range_plus_commit_allowance(store):
    directory, conn = store
    start = NOW - 3600 * NSEC
    for index in range(720):
        sampled = start + index * 5 * NSEC
        host: dict[str, object] = {"cpu_busy_pct": 1}
        if index % 3 == 0:
            host["gpu"] = {"provider": "nvidia-smi", "availability": "ok",
                           "observed_at_ns": sampled, "max_utilization_pct": 20}
        _sample(conn, when=sampled, host=host)
    conn.commit()
    reader = MonitorReader(directory)
    first = reader.series("gpu_max_utilization_pct", since=start, until=NOW,
                          step=15, limit=10, now=NOW)
    assert first["next_cursor"]
    assert first["coverage"]["raw_samples"] <= 36
    assert first["coverage"]["commit_lookahead_seconds"] == 10
    second = reader.series("gpu_max_utilization_pct", since=start, until=NOW,
                           step=15, limit=10, cursor=first["next_cursor"], now=NOW)
    assert second["coverage"]["raw_samples"] <= 36
    assert second["items"][0]["sampled_at"] > first["items"][-1]["sampled_at"]


def test_gpu_default_budget_pages_32_devices_without_losing_rows(store):
    directory, conn = store
    devices = [{"index": index, "name": f"GPU {index}", "utilization_pct": index,
                "memory_used_bytes": 1024, "memory_total_bytes": 4096,
                "temperature_c": 40, "power_w": 80} for index in range(32)]
    _sample(conn, when=NOW, host={"gpu": {"provider": "nvidia-smi", "availability": "ok",
                                          "observed_at_ns": NOW, "devices_seen": 32,
                                          "devices_scanned": 32, "devices": devices}})
    conn.commit()
    reader = MonitorReader(directory)
    cursor = None
    seen = []
    for _ in range(32):
        page = reader.gpu(cursor=cursor, now=NOW)
        assert len(encode_budgeted_json(page, 4096).encode()) <= 4096
        seen.extend(item["identity"]["index"] for item in page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert seen == list(range(32))
    assert cursor is None


def test_rollups_reject_unaligned_long_range_and_raw_short_range_excludes_them(store):
    directory, conn = store
    start = NOW - 3 * 24 * 60 * 60 * NSEC
    conn.execute("INSERT INTO host_rollups VALUES(?,?,?,?)",
                 (start, 12, json.dumps({"cpu_busy_pct": {"min": 90, "max": 90,
                                                          "mean": 90, "last": 90, "valid_count": 12}}), "{}"))
    _sample(conn, when=NOW - 30 * NSEC, host={"cpu_busy_pct": 12})
    conn.commit()
    with pytest.raises(MonitorQueryError, match="minute-aligned"):
        MonitorReader(directory).series("cpu_busy_pct", since=start + 30 * NSEC,
                                        until=NOW, step=60, now=NOW)
    exact = MonitorReader(directory).series("cpu_busy_pct", since=NOW - 90 * NSEC,
                                           until=NOW - 10 * NSEC, step=60, now=NOW)
    assert [item["value"]["last"] if item["value"] else None for item in exact["items"]] == [None, 12]
    assert exact["coverage"]["raw_samples"] == 1


def test_process_gap_identity_filter_and_leaders_only(store):
    directory, conn = store
    rows = [
        {"pid": 11, "start_ticks": 90, "name": "worker", "user": "a", "service": "api",
         "cpu_user_ns": 10, "cpu_system_ns": 5, "rss_bytes": 100, "read_bytes": None,
         "write_bytes": None, "leader_reasons": ["rss"]},
        {"pid": 11, "start_ticks": 100, "name": "worker", "user": "b", "service": "api",
         "cpu_user_ns": 30, "cpu_system_ns": 5, "rss_bytes": 200, "read_bytes": 4,
         "write_bytes": 4, "leader_reasons": ["cpu"]},
    ]
    _sample(conn, when=NOW - 20 * NSEC, processes=rows)
    conn.commit()
    reader = MonitorReader(directory)
    result = reader.processes(at=NOW, name="worker", user="b", sort="cpu", now=NOW)
    assert result["coverage"]["leaders_only"] is True
    assert result["items"][0]["identity"] == {"boot_id": "boot-a", "pid": 11, "start_ticks": 100}
    assert result["items"][0]["availability"] == "leaders_only"
    gap = reader.processes(at=NOW + 11 * NSEC, now=NOW + 11 * NSEC)
    assert gap["items"] == []
    assert gap["errors"][0]["code"] == "not_collected"


def test_unstored_process_filter_is_explicitly_unsupported(store):
    directory, conn = store
    _sample(conn, when=NOW, processes=[{"pid": 1, "start_ticks": 1, "name": "worker",
                                        "rss_bytes": 10}])
    conn.commit()
    result = MonitorReader(directory).processes(user="owner", now=NOW)
    assert result["items"] == []
    assert result["coverage"]["availability"] == "unsupported"
    assert result["errors"][0]["code"] == "unsupported"


def test_user_filter_matches_name_or_uid_and_reports_partial_attribution(store):
    directory, conn = store
    rows = [
        {"pid": 1, "start_ticks": 1, "name": "a", "uid": 1000, "user": "alice", "rss_bytes": 10},
        {"pid": 2, "start_ticks": 2, "name": "b", "uid": 1001, "user": None, "rss_bytes": 20},
        {"pid": 3, "start_ticks": 3, "name": "c", "uid": None, "user": None, "rss_bytes": 30},
    ]
    _sample(conn, when=NOW, processes=rows)
    conn.commit()
    reader = MonitorReader(directory)
    by_name = reader.processes(user="alice", now=NOW)
    assert [item["identity"]["pid"] for item in by_name["items"]] == [1]
    assert by_name["coverage"]["user_attribution"] == {
        "username_unknown": 2, "uid_unknown": 1, "partial": True}
    assert by_name["errors"][0]["code"] == "partial_attribution"
    by_uid = reader.processes(user="1001", now=NOW)
    assert [item["identity"]["pid"] for item in by_uid["items"]] == [2]
    assert by_uid["coverage"]["user_attribution"]["partial"] is True


def test_denied_process_scan_is_not_an_observed_empty_set(store):
    directory, conn = store
    _sample(conn, when=NOW, processes=[], denied=3)
    conn.commit()
    result = MonitorReader(directory).processes(now=NOW)
    assert result["coverage"]["availability"] == "permission_denied"
    assert result["errors"][0]["code"] == "permission_denied"


def test_process_cursor_pins_sample_and_cpu_uses_interval_delta(store):
    directory, conn = store
    first_rows = [
        {"pid": 1, "start_ticks": 1, "name": "old", "cpu_user_ns": 1000,
         "cpu_system_ns": 0, "rss_bytes": 10, "read_bytes": 0, "write_bytes": 0,
         "observed_monotonic_ns": 10 * NSEC},
        {"pid": 2, "start_ticks": 2, "name": "fast", "cpu_user_ns": 10,
         "cpu_system_ns": 0, "rss_bytes": 10, "read_bytes": 0, "write_bytes": 0,
         "observed_monotonic_ns": 10 * NSEC},
    ]
    second_rows = [
        {**first_rows[0], "cpu_user_ns": 1001, "observed_monotonic_ns": 15 * NSEC},
        {**first_rows[1], "cpu_user_ns": 110, "observed_monotonic_ns": 15 * NSEC},
    ]
    _sample(conn, when=NOW - 10 * NSEC, processes=first_rows)
    _sample(conn, when=NOW - 5 * NSEC, processes=second_rows)
    conn.commit()
    reader = MonitorReader(directory)
    first = reader.processes(sort="cpu", limit=1, now=NOW)
    assert first["items"][0]["identity"]["pid"] == 2
    assert first["items"][0]["sort_value"] == pytest.approx(0.000002)
    assert first["items"][0]["unit"] == "%"
    _sample(conn, when=NOW, processes=[])
    conn.commit()
    second = reader.processes(sort="cpu", limit=1, cursor=first["next_cursor"], now=NOW + NSEC)
    assert second["items"][0]["identity"]["pid"] == 1
    assert second["items"][0]["sort_value"] == pytest.approx(0.00000002)


def test_process_tree_pages_one_detail_observation_with_ancestry_and_gaps(store):
    directory, conn = store
    rows = [
        {"pid": 21, "ppid": 10, "start_ticks": 21, "name": "child", "rss_bytes": 20},
        {"pid": 10, "ppid": 1, "start_ticks": 10, "name": "parent", "rss_bytes": 10},
        {"pid": 30, "ppid": 999, "start_ticks": 30, "name": "orphan", "rss_bytes": 30},
        {"pid": 22, "ppid": 21, "start_ticks": 22, "name": "grandchild", "rss_bytes": 22},
    ]
    _sample(conn, when=NOW, mode="detail", processes=rows, denied=1)
    conn.commit()
    reader = MonitorReader(directory)
    first = reader.processes(view="tree", limit=1, max_bytes=4096, now=NOW)
    assert [item["identity"]["pid"] for item in first["items"]] == [10]
    assert first["items"][0]["tree"]["parent_link"] == "unavailable_in_capture"
    assert first["coverage"]["tree"]["permission_denied"] == 1
    assert first["coverage"]["tree"]["unavailable_parent_links"] == 2
    assert first["next_cursor"]
    second = reader.processes(view="tree", limit=1, cursor=first["next_cursor"], now=NOW + NSEC)
    assert [item["identity"]["pid"] for item in second["items"]] == [21]
    third = reader.processes(view="tree", limit=1, cursor=second["next_cursor"], now=NOW + NSEC)
    assert [item["identity"]["pid"] for item in third["items"]] == [22]
    assert second["items"][0]["tree"] == {
        "depth": 1, "children": 1, "parent_link": "linked",
        "parent_identity": {"boot_id": "boot-a", "pid": 10, "start_ticks": 10},
    }
    _sample(conn, when=NOW + NSEC, mode="detail", processes=[])
    conn.commit()
    returned_first = reader.processes(view="tree", limit=1,
                                      cursor=first["coverage"]["observation_cursor"],
                                      now=NOW + 2 * NSEC)
    assert returned_first["items"][0]["identity"]["pid"] == 10
    fourth = reader.processes(view="tree", limit=1, cursor=third["next_cursor"], now=NOW + 2 * NSEC)
    assert [item["identity"]["pid"] for item in fourth["items"]] == [30]
    assert fourth["coverage"]["tree"]["sample_id"] == first["coverage"]["tree"]["sample_id"]
    with pytest.raises(MonitorQueryError, match="cursor"):
        reader.processes(view="list", limit=1, cursor=first["next_cursor"], now=NOW + NSEC)
    filtered = reader.processes(at=NOW, view="tree", name="child", now=NOW)
    assert filtered["items"][0]["tree"]["parent_link"] == "filtered_out"


def test_process_tree_requires_same_observation_and_respects_byte_budget(store):
    directory, conn = store
    rows = [
        {"pid": 1, "ppid": 0, "start_ticks": 1, "name": "root", "rss_bytes": 3,
         "observed_at_ns": NOW - NSEC},
        {"pid": 2, "ppid": 1, "start_ticks": 2, "name": "later", "rss_bytes": 2,
         "observed_at_ns": NOW},
    ]
    _sample(conn, when=NOW, mode="detail", processes=rows)
    conn.commit()
    reader = MonitorReader(directory)
    result = reader.processes(view="tree", max_bytes=2048, now=NOW)
    assert len(encode_budgeted_json(result, 2048).encode()) <= 2048
    items = list(result["items"])
    if result["next_cursor"]:
        second = reader.processes(view="tree", max_bytes=2048,
                                  cursor=result["next_cursor"], now=NOW)
        assert len(encode_budgeted_json(second, 2048).encode()) <= 2048
        items.extend(second["items"])
    later = next(item for item in items if item["identity"]["pid"] == 2)
    assert later["tree"]["parent_link"] == "identity_or_observation_mismatch"
    with pytest.raises(MonitorQueryError, match="view"):
        reader.processes(view="graph", now=NOW)


def test_process_tree_order_survives_prior_rate_sample_eviction(store):
    directory, conn = store
    prior = [
        {"pid": 1, "ppid": 0, "start_ticks": 1, "name": "first", "rss_bytes": 1,
         "cpu_user_ns": 1, "cpu_system_ns": 0, "observed_monotonic_ns": NSEC},
        {"pid": 2, "ppid": 0, "start_ticks": 2, "name": "second", "rss_bytes": 1,
         "cpu_user_ns": 1, "cpu_system_ns": 0, "observed_monotonic_ns": NSEC},
    ]
    current = [{**prior[0], "cpu_user_ns": 2, "observed_monotonic_ns": 2 * NSEC},
               {**prior[1], "cpu_user_ns": 100, "observed_monotonic_ns": 2 * NSEC}]
    _sample(conn, when=NOW - NSEC, mode="detail", processes=prior)
    _sample(conn, when=NOW, mode="detail", processes=current)
    conn.commit()
    reader = MonitorReader(directory)
    first = reader.processes(view="tree", sort="cpu", limit=1, now=NOW)
    assert first["items"][0]["identity"]["pid"] == 1
    assert first["items"][0]["sort_value"] is not None
    conn.execute("DELETE FROM samples WHERE sampled_at_ns=?", (NOW - NSEC,))
    conn.commit()
    second = reader.processes(view="tree", sort="cpu", limit=1,
                              cursor=first["next_cursor"], now=NOW + NSEC)
    assert second["items"][0]["identity"]["pid"] == 2
    assert second["items"][0]["sort_value"] is None
    assert second["coverage"]["tree"]["sample_id"] == first["coverage"]["tree"]["sample_id"]


def test_process_tree_cursor_rejects_reused_sqlite_sample_id(store):
    directory, conn = store
    rows = [{"pid": pid, "ppid": 0, "start_ticks": pid, "name": str(pid), "rss_bytes": pid}
            for pid in (1, 2)]
    _sample(conn, when=NOW, mode="detail", processes=rows)
    conn.commit()
    reader = MonitorReader(directory)
    first = reader.processes(view="tree", limit=1, now=NOW)
    old_id = first["coverage"]["tree"]["sample_id"]
    assert first["next_cursor"]
    conn.execute("DELETE FROM samples")
    _sample(conn, when=NOW + NSEC, mode="detail", processes=rows, boot="boot-b")
    conn.commit()
    assert conn.execute("SELECT id FROM samples").fetchone()[0] == old_id
    resumed = reader.processes(view="tree", limit=1, cursor=first["next_cursor"], now=NOW + NSEC)
    assert resumed["items"] == []
    assert resumed["coverage"]["availability"] == "retention_expired"
    assert resumed["errors"][0]["code"] == "retention_expired"


def test_cached_process_observation_age_and_distinct_interval(store):
    directory, conn = store
    old = {"pid": 3, "start_ticks": 3, "name": "cached", "rss_bytes": 10,
           "cpu_user_ns": 10, "cpu_system_ns": 0, "read_bytes": 0,
           "write_bytes": 0, "observed_at_ns": NOW - 15 * NSEC,
           "observed_monotonic_ns": 10 * NSEC}
    new = {**old, "cpu_user_ns": 20, "observed_at_ns": NOW - 5 * NSEC,
           "observed_monotonic_ns": 20 * NSEC}
    _sample(conn, when=NOW - 15 * NSEC, processes=[old])
    _sample(conn, when=NOW - 10 * NSEC, processes=[old])
    _sample(conn, when=NOW - 5 * NSEC, processes=[new])
    _sample(conn, when=NOW, processes=[new])
    conn.commit()
    result = MonitorReader(directory).processes(sort="cpu", now=NOW)
    assert result["items"][0]["observed_at"].endswith("11:59:55.000000000Z")
    assert result["items"][0]["observation_age_seconds"] == 5
    assert result["items"][0]["sort_value"] == pytest.approx(0.0000001)


def test_event_cursor_binds_filters_and_budget(store):
    directory, conn = store
    for index in range(5):
        conn.execute("INSERT INTO events(sampled_at_ns,kind,severity,entity,details_json) VALUES(?,?,?,?,?)",
                     (NOW - index * NSEC, "failure", "warning", "api", json.dumps({"n": index})))
    conn.commit()
    reader = MonitorReader(directory)
    first = reader.events(since=NOW - 10 * NSEC, until=NOW + NSEC, kind="failure",
                          limit=2, max_bytes=1000, now=NOW)
    assert [item["details"]["n"] for item in first["items"]] == [0, 1]
    assert first["truncated"] is True and first["next_cursor"]
    second = reader.events(since=NOW - 10 * NSEC, until=NOW + NSEC, kind="failure",
                           limit=2, cursor=first["next_cursor"], now=NOW)
    assert [item["details"]["n"] for item in second["items"]] == [2, 3]
    with pytest.raises(MonitorQueryError):
        reader.events(since=NOW - 10 * NSEC, until=NOW + NSEC, kind="other",
                      cursor=first["next_cursor"], now=NOW)
    with pytest.raises(MonitorQueryError):
        reader.events(since=NOW - 10 * NSEC, until=NOW + NSEC, cursor="bad!", now=NOW)


def test_schema_mismatch_and_whitelist(store):
    directory, conn = store
    conn.execute("UPDATE meta SET value='2' WHERE key='schema_version'")
    conn.commit()
    with pytest.raises(MonitorSchemaError):
        MonitorReader(directory).status(now=NOW)
    with pytest.raises(MonitorQueryError):
        MonitorReader(directory).series("secret_command", now=NOW)
