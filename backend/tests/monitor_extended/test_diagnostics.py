from __future__ import annotations

import gzip
import json
import sqlite3
from pathlib import Path

import pytest

from monitor_extended import benchmark, disk, export_capture, query_disk_space, run_benchmark
from monitor_observe import ObserveQueryError
from monitor_reader import MonitorReader


def _bounded(payload: dict, budget: int = 4096) -> None:
    assert set(payload) == {"schema", "generated_at", "requested", "coverage", "items",
                            "next_cursor", "truncated", "errors"}
    assert len(json.dumps(payload, separators=(",", ":")).encode()) <= budget


def test_disk_scan_scope_redaction_links_and_partial(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
    monkeypatch.setattr(disk, "PROJECT_ROOT", root)
    monkeypatch.setattr(disk.Path, "home", lambda: tmp_path / "home")
    result = query_disk_space(root)
    _bounded(result)
    names = [entry["value"]["name"] for entry in result["items"]]
    assert names == ["visible.txt", "nested", "project.identity.json"] or set(names) == {"visible.txt", "nested", "project.identity.json"}
    assert "link" not in names
    assert "secret" not in json.dumps(result).lower()
    assert result["coverage"]["bytes_observed"] == 8 + (root / "project.identity.json").stat().st_size
    assert result["coverage"]["complete"] is False
    assert result["coverage"]["stop_reason"] == "excluded_entries"
    partial = query_disk_space(root, max_entries=1)
    assert partial["truncated"]
    assert partial["coverage"]["stop_reason"] == "entry_cap"
    cancelled = query_disk_space(root, cancelled=lambda: True)
    assert cancelled["coverage"]["stop_reason"] == "cancelled"
    with pytest.raises(ObserveQueryError):
        query_disk_space(outside)
    linked = query_disk_space(root / "link")
    assert linked["coverage"]["complete"] is False
    assert linked["items"] == []


def test_configured_project_root_requires_identity_and_no_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "checkout"
    root.mkdir()
    (root / "project.identity.json").write_text('{"project":{"id":"summitflow"}}')
    (root / "visible.txt").write_bytes(b"123")
    monkeypatch.setattr(disk, "PROJECT_ROOT", tmp_path / "absent")
    monkeypatch.setattr(disk.Path, "home", lambda: tmp_path / "home")
    monkeypatch.setenv("SUMMITFLOW_HOST_CONFIG_ROOT", str(root))
    assert query_disk_space(root)["coverage"]["scope"] == "project"
    (root / "project.identity.json").write_text('{"project":{"id":"other"}}')
    with pytest.raises(ObserveQueryError):
        query_disk_space(root)
    (root / "project.identity.json").write_text('{"project":{"id":"summitflow"}}')
    alias = tmp_path / "alias"
    alias.symlink_to(root, target_is_directory=True)
    monkeypatch.setenv("SUMMITFLOW_HOST_CONFIG_ROOT", str(alias))
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
            kind TEXT NOT NULL,severity TEXT NOT NULL,entity TEXT);
    """)
    process = [{"pid": pid, "start_ticks": pid * 10, "name": "sensitive-command", "user": "private-user",
                "rss_bytes": rss, "cpu_user_ns": 20, "cpu_system_ns": 10}
               for pid, rss in ((123, 100), (126, 50), (125, 300), (124, 200))]
    for index, mode in ((1, "baseline"), (2, "detail")):
        db.execute("INSERT INTO samples VALUES(?,?,?,?,?,?,?,?,?)",
                   (index, index * 20_000_000_000, mode, "boot-a",
                    json.dumps({"cpu_busy_pct": 30, "secret": "do-not-export"}),
                    gzip.compress(json.dumps(process).encode()), 1, 0, "[]"))
    db.execute("INSERT INTO events VALUES(1,?,?,?,?)",
               (40_000_000_000, "capture_start", "info", "sensitive-service"))
    db.commit()
    db.close()
    return MonitorReader(tmp_path)


def test_export_replay_redacts_and_paginates(tmp_path: Path) -> None:
    reader = _reader(tmp_path)
    first = export_capture(reader, 0, 60_000_000_000, limit=2)
    _bounded(first)
    assert first["truncated"] and first["next_cursor"]
    assert [row["type"] for row in first["items"]] == ["event", "sample"]
    assert first["items"][1]["process_coverage"]["leaders_only"] is False
    assert [process["pid"] for process in first["items"][1]["processes"]] == [125, 124, 123]
    assert first["items"][1]["processes"][0]["start_ticks"] == 1250
    assert len(first["items"][1]["boot_ref"]) == 16
    assert first["items"][1]["process_query"]["sort"] == "rss"
    second = export_capture(reader, 0, 60_000_000_000, limit=2, cursor=first["next_cursor"])
    assert second["items"][0]["process_coverage"]["leaders_only"] is True
    assert second["items"][0]["gap_to_next_seconds"] == 20
    raw = json.dumps([first, second])
    assert "sensitive" not in raw and "do-not-export" not in raw and "private-user" not in raw
    complete = export_capture(reader, 0, 60_000_000_000, limit=3, max_bytes=8192)
    assert complete["coverage"]["gaps_in_page"] == 1
    assert complete["items"][-1]["gap_to_next_seconds"] == 20
    with pytest.raises(ObserveQueryError):
        export_capture(reader, 0, 60_000_000_000, cursor="bad")
    with pytest.raises(ObserveQueryError):
        export_capture(reader, 0, 60_000_000_000, limit=21)
    with sqlite3.connect(tmp_path / "monitor.sqlite3") as conn:
        conn.execute("INSERT INTO events VALUES(2,?,?,?,?)",
                     (30_000_000_000, "secret-token", "info", "private-service"))
    redacted_kind = export_capture(reader, 25_000_000_000, 35_000_000_000)
    assert redacted_kind["items"][0]["kind"] == "redacted"
    assert "private-service" not in json.dumps(redacted_kind)
