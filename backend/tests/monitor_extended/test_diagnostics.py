from __future__ import annotations

import gzip
import json
import sqlite3
from pathlib import Path

import pytest

from monitor_extended import benchmark, export_capture, query_disk_space, run_benchmark
from monitor_observe import ObserveQueryError
from monitor_reader import MonitorReader


def _bounded(payload: dict, budget: int = 4096) -> None:
    assert set(payload) == {"schema", "generated_at", "requested", "coverage", "items",
                            "next_cursor", "truncated", "errors"}
    assert len(json.dumps(payload, separators=(",", ":")).encode()) <= budget


def test_disk_scan_is_system_wide_and_never_follows_links(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    (root / "project.identity.json").write_text('{"project":{"id":"summitflow"}}')
    (root / "visible.txt").write_bytes(b"12345")
    (root / ".hidden").write_bytes(b"hidden")
    (root / "secret-token.txt").write_bytes(b"private")
    (root / "nested").mkdir()
    (root / "nested" / "child.txt").write_bytes(b"123")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "large.txt").write_bytes(b"x" * 100)
    (root / "link").symlink_to(outside, target_is_directory=True)
    result = query_disk_space(root)
    _bounded(result)
    names = [entry["value"]["name"] for entry in result["items"]]
    assert set(names) == {"visible.txt", "nested", "project.identity.json", ".hidden", "secret-token.txt"}
    assert "link" not in names
    assert "secret-token.txt" in json.dumps(result)
    assert result["coverage"]["bytes_observed"] == 5 + 6 + 7 + 3 + (root / "project.identity.json").stat().st_size
    assert result["coverage"]["complete"] is False
    assert result["coverage"]["stop_reason"] == "excluded_entries"
    partial = query_disk_space(root, max_entries=1)
    assert partial["truncated"]
    assert partial["coverage"]["stop_reason"] == "entry_cap"
    cancelled = query_disk_space(root, cancelled=lambda: True)
    assert cancelled["coverage"]["stop_reason"] == "cancelled"
    assert query_disk_space(outside)["items"][0]["value"]["name"] == "large.txt"
    with pytest.raises(ObserveQueryError, match="symlink"):
        query_disk_space(root / "link")


def test_disk_scan_accepts_arbitrary_mount_paths_but_rejects_symlink_alias(tmp_path: Path) -> None:
    root = tmp_path / "checkout"
    root.mkdir()
    (root / "project.identity.json").write_text('{"project":{"id":"summitflow"}}')
    (root / "visible.txt").write_bytes(b"123")
    assert query_disk_space(root)["coverage"]["scope"] == "mount"
    (root / "project.identity.json").write_text('{"project":{"id":"other"}}')
    assert query_disk_space(root)["items"]
    alias = tmp_path / "alias"
    alias.symlink_to(root, target_is_directory=True)
    with pytest.raises(ObserveQueryError):
        query_disk_space(alias)


def test_benchmarks_are_bounded_and_unsupported_is_explicit(tmp_path: Path,
                                                             monkeypatch: pytest.MonkeyPatch) -> None:
    identity = tmp_path / "project.identity.json"
    identity.write_text("{}")
    monkeypatch.setattr(benchmark, "PROJECT_IDENTITY", identity)
    cpu = run_benchmark("cpu", duration_seconds=0.01)
    _bounded(cpu)
    assert cpu["items"][0]["value"]["bytes_processed"] <= benchmark.MAX_WORK_BYTES
    assert cpu["items"][0]["value"]["process_cpu_seconds"] >= 0
    reading = run_benchmark("disk", duration_seconds=0.01)
    assert reading["items"][0]["value"]["source"] == "project.identity.json"
    assert reading["coverage"]["cache_affected"] is True
    identity.unlink()
    assert run_benchmark("disk")["coverage"]["availability"] == "unsupported"
    assert run_benchmark("gpu")["coverage"]["availability"] == "unsupported"
    assert run_benchmark("network")["items"] == []
    with pytest.raises(ObserveQueryError):
        run_benchmark("cpu", duration_seconds=10)


def _reader(tmp_path: Path) -> MonitorReader:
    db = sqlite3.connect(tmp_path / "monitor.sqlite3")
    db.executescript("""
        CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        INSERT INTO meta VALUES('schema_version','1');
        CREATE TABLE samples(id INTEGER PRIMARY KEY,sampled_at_ns INTEGER NOT NULL,
            mode TEXT NOT NULL,boot_id TEXT NOT NULL,host_json TEXT NOT NULL,process_blob BLOB NOT NULL,
            processes_seen INTEGER NOT NULL,processes_permission_denied INTEGER NOT NULL,
            errors_json TEXT NOT NULL);
        CREATE TABLE events(id INTEGER PRIMARY KEY,sampled_at_ns INTEGER NOT NULL,
            kind TEXT NOT NULL,severity TEXT NOT NULL,entity TEXT,details_json TEXT NOT NULL);
    """)
    process = [{"pid": pid, "start_ticks": pid * 10, "name": "sensitive-command", "user": "private-user",
                "rss_bytes": rss, "cpu_user_ns": 20, "cpu_system_ns": 10}
               for pid, rss in ((123, 100), (126, 50), (125, 300), (124, 200))]
    for index, mode in ((1, "baseline"), (2, "detail")):
        db.execute("INSERT INTO samples VALUES(?,?,?,?,?,?,?,?,?)",
                   (index, index * 20_000_000_000, mode, "boot-a",
                    json.dumps({"cpu_busy_pct": 30, "secret": "do-not-export"}),
                    gzip.compress(json.dumps(process).encode()), 1, 0, "[]"))
    db.execute("INSERT INTO events VALUES(1,?,?,?,?,?)",
               (40_000_000_000, "capture_start", "info", "sensitive-service",
                '{"service":"sensitive-service","token":"do-not-export"}'))
    db.commit()
    db.close()
    return MonitorReader(tmp_path)


def test_export_replay_shows_event_details_and_paginates(tmp_path: Path) -> None:
    reader = _reader(tmp_path)
    first = export_capture(reader, 0, 60_000_000_000, limit=2)
    _bounded(first)
    assert first["truncated"] and first["next_cursor"]
    assert [row["type"] for row in first["items"]] == ["event", "sample"]
    assert first["items"][0]["entity"] == "sensitive-service"
    assert first["items"][0]["details"]["service"] == "sensitive-service"
    assert first["items"][0]["details"]["token"] == "[REDACTED CREDENTIAL]"
    assert first["items"][1]["process_coverage"]["leaders_only"] is False
    assert [process["pid"] for process in first["items"][1]["processes"]] == [125, 124, 123]
    assert first["items"][1]["processes"][0]["start_ticks"] == 1250
    assert len(first["items"][1]["boot_ref"]) == 16
    assert first["items"][1]["process_query"]["sort"] == "rss"
    second = export_capture(reader, 0, 60_000_000_000, limit=2, cursor=first["next_cursor"])
    assert second["items"][0]["process_coverage"]["leaders_only"] is True
    assert second["items"][0]["gap_to_next_seconds"] == 20
    raw = json.dumps([first, second])
    assert "sensitive-service" in raw and "do-not-export" not in raw and "private-user" not in raw
    complete = export_capture(reader, 0, 60_000_000_000, limit=3, max_bytes=8192)
    assert complete["coverage"]["gaps_in_page"] == 1
    assert complete["items"][-1]["gap_to_next_seconds"] == 20
    with pytest.raises(ObserveQueryError):
        export_capture(reader, 0, 60_000_000_000, cursor="bad")
    with pytest.raises(ObserveQueryError):
        export_capture(reader, 0, 60_000_000_000, limit=21)
    with sqlite3.connect(tmp_path / "monitor.sqlite3") as conn:
        conn.execute("INSERT INTO events VALUES(2,?,?,?,?,?)",
                     (30_000_000_000, "service_diagnostic", "info", "private-service", '{}'))
    event = export_capture(reader, 25_000_000_000, 35_000_000_000)
    assert event["items"][0]["kind"] == "service_diagnostic"
    assert event["items"][0]["entity"] == "private-service"
