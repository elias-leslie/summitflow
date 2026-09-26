#!/usr/bin/env python3
"""Compare finite host-collector prototypes under one output and storage workload."""

from __future__ import annotations

import argparse
import json
import os
import platform
import queue
import resource
import sqlite3
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

import psutil

HOST_FIELDS = (
    "cpu_busy_pct",
    "memory_total_bytes",
    "memory_available_bytes",
    "swap_used_bytes",
    "disk_total_bytes",
    "disk_free_bytes",
    "cpu_some_avg10_pct",
    "memory_some_avg10_pct",
    "io_some_avg10_pct",
    "net_rx_bytes",
    "net_tx_bytes",
    "disk_read_bytes",
    "disk_write_bytes",
)
PROCESS_FIELDS = (
    "pid",
    "start_ticks",
    "name",
    "cpu_user_ns",
    "cpu_system_ns",
    "rss_bytes",
    "read_bytes",
    "write_bytes",
    "leader_reasons",
)
SERVICE_FIELDS = ("source", "cpu_usage_usec", "memory_current_bytes", "io_read_bytes", "io_write_bytes")


def _cpu_snapshot(pid: int) -> dict[str, float] | None:
    try:
        times = psutil.Process(pid).cpu_times()
    except (psutil.Error, OSError):
        return None
    return {"user_s": times.user, "system_s": times.system}


def _validate_sample(sample: dict[str, Any], mode: str, service_expected: bool) -> list[str]:
    issues = [f"missing host.{key}" for key in HOST_FIELDS if key not in sample["host"]]
    processes = sample["processes"]
    if mode == "detail" and len(processes) + sample.get("processes_exited", 0) < sample["processes_seen"]:
        issues.append("detail omitted visible processes")
    for process in processes:
        issues.extend(f"missing process.{key}" for key in PROCESS_FIELDS if key not in process)
        if mode == "detail" and process.get("leader_reasons"):
            issues.append("detail process has leader reasons")
    if service_expected:
        service = sample.get("service")
        if not isinstance(service, dict):
            issues.append("missing service")
        else:
            issues.extend(f"missing service.{key}" for key in SERVICE_FIELDS if key not in service)
    if not isinstance(sample.get("errors"), list):
        issues.append("missing errors list")
    return issues


def _process_io(pid: int) -> dict[str, int]:
    try:
        values = psutil.Process(pid).io_counters()
    except (psutil.Error, OSError):
        return {}
    return {
        "rchar": values.read_chars,
        "wchar": values.write_chars,
        "read_bytes": values.read_bytes,
        "write_bytes": values.write_bytes,
        "syscr": values.read_count,
        "syscw": values.write_count,
    }


def _poll_processes(pid: int, stop: threading.Event, peaks: dict[str, Any]) -> None:
    while not stop.is_set():
        try:
            root = psutil.Process(pid)
            family = [root, *root.children(recursive=True)]
        except (psutil.Error, OSError):
            family = []
        rss = 0
        cpu_user_s = 0.0
        cpu_system_s = 0.0
        io: dict[str, int] = {}
        for process in family:
            try:
                rss += process.memory_info().rss
                cpu = process.cpu_times()
                cpu_user_s += cpu.user
                cpu_system_s += cpu.system
                counters = _process_io(process.pid)
            except (psutil.Error, OSError):
                continue
            for key, value in counters.items():
                io[key] = io.get(key, 0) + value
        peaks["rss_bytes"] = max(peaks["rss_bytes"], rss)
        peaks["cpu_user_s"] = max(peaks["cpu_user_s"], cpu_user_s)
        peaks["cpu_system_s"] = max(peaks["cpu_system_s"], cpu_system_s)
        for key, value in io.items():
            peaks["io"][key] = max(peaks["io"].get(key, 0), value)
        stop.wait(0.1)


def _read_stdout(pipe: Any, output: queue.Queue[str | None]) -> None:
    for line in pipe:
        output.put(line)
    output.put(None)


def _db_size(path: Path) -> dict[str, int]:
    return {
        suffix or "db": file.stat().st_size if file.exists() else 0
        for suffix, file in (
            ("", path),
            ("wal", Path(f"{path}-wal")),
            ("shm", Path(f"{path}-shm")),
        )
    }


def _run(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    db_path = output_dir / "samples.sqlite3"
    if db_path.exists() or (output_dir / "samples.ndjson").exists():
        raise ValueError(f"benchmark output already exists in {output_dir}")
    connection = sqlite3.connect(db_path)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=NORMAL")
    connection.execute(
        "CREATE TABLE IF NOT EXISTS samples (sequence INTEGER PRIMARY KEY, sampled_at TEXT NOT NULL, mode TEXT NOT NULL, payload TEXT NOT NULL)"
    )
    connection.commit()

    command = [
        str(args.collector.resolve()),
        "--mode",
        args.mode,
        "--samples",
        str(args.samples),
        "--interval-ms",
        str(args.interval_ms),
    ]
    if args.service_cgroup:
        command.extend(("--service-cgroup", str(args.service_cgroup.resolve())))

    errors: list[str] = []
    seen = 0
    durations_ns: list[int] = []
    commit_wall_ns: list[int] = []
    received_monotonic_ns: list[int] = []
    collector_cpu_at_sample: list[dict[str, float] | None] = []
    process_counts: list[int] = []
    process_rows: list[int] = []
    process_io_available: list[int] = []
    sample_source_errors: list[list[dict[str, Any]]] = []
    host_availability: dict[str, int] = {key: 0 for key in HOST_FIELDS}
    output_bytes = 0
    sqlite_cpu_s = 0.0
    peaks: dict[str, Any] = {"rss_bytes": 0, "cpu_user_s": 0.0, "cpu_system_s": 0.0, "io": {}}
    output_lines: queue.Queue[str | None] = queue.Queue()
    stop = threading.Event()
    start_wall = time.time()
    start_mono = time.monotonic()
    writer_cpu_start = time.process_time()
    writer_io_start = _process_io(os.getpid())
    child_usage_start = resource.getrusage(resource.RUSAGE_CHILDREN)
    with (output_dir / "collector.stderr.log").open("w") as stderr_file:
        process = subprocess.Popen(
            command,
            cwd=args.collector.parent,
            stdout=subprocess.PIPE,
            stderr=stderr_file,
            text=True,
            bufsize=1,
        )
        assert process.stdout is not None
        reader = threading.Thread(target=_read_stdout, args=(process.stdout, output_lines), daemon=True)
        monitor = threading.Thread(target=_poll_processes, args=(process.pid, stop, peaks), daemon=True)
        reader.start()
        monitor.start()
        # Finite --samples should terminate. This bound catches a stuck provider or child.
        deadline = start_mono + (args.samples + 2) * args.interval_ms / 1000 + 30
        with (output_dir / "samples.ndjson").open("w") as raw_file:
            while seen < args.samples and time.monotonic() < deadline:
                try:
                    line = output_lines.get(timeout=min(1.0, max(0.01, deadline - time.monotonic())))
                except queue.Empty:
                    if process.poll() is not None and output_lines.empty():
                        break
                    continue
                if line is None:
                    break
                received_ns = time.monotonic_ns()
                cpu_at_sample = _cpu_snapshot(process.pid)
                output_bytes += len(line.encode("utf-8"))
                raw_file.write(line)
                try:
                    sample = json.loads(line)
                    if sample.get("schema") != 1 or sample.get("mode") != args.mode:
                        raise ValueError("unexpected sample schema or mode")
                    sampled_at = sample["sampled_at"]
                    duration_ns = int(sample["duration_ns"])
                    process_count = int(sample["processes_seen"])
                    if not isinstance(sample.get("host"), dict) or not isinstance(sample.get("processes"), list):
                        raise ValueError("missing host or processes")
                    sample_issues = _validate_sample(sample, args.mode, bool(args.service_cgroup))
                    if sample_issues:
                        raise ValueError("; ".join(sorted(set(sample_issues))))
                except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
                    errors.append(f"sample {seen + 1}: {exc}")
                    continue
                seen += 1
                durations_ns.append(duration_ns)
                received_monotonic_ns.append(received_ns)
                collector_cpu_at_sample.append(cpu_at_sample)
                process_counts.append(process_count)
                process_rows.append(len(sample["processes"]))
                process_io_available.append(
                    sum(row["read_bytes"] is not None and row["write_bytes"] is not None for row in sample["processes"])
                )
                sample_source_errors.append(sample["errors"])
                for key in HOST_FIELDS:
                    host_availability[key] += sample["host"][key] is not None
                commit_start = time.monotonic_ns()
                write_cpu_start = time.thread_time()
                connection.execute(
                    "INSERT INTO samples (sequence, sampled_at, mode, payload) VALUES (?, ?, ?, ?)",
                    (seen, sampled_at, args.mode, line.rstrip("\n")),
                )
                connection.commit()
                sqlite_cpu_s += time.thread_time() - write_cpu_start
                commit_wall_ns.append(time.monotonic_ns() - commit_start)

        if process.poll() is None and seen < args.samples:
            process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            errors.append("collector did not exit after termination")
        stop.set()
        reader.join(timeout=1)
        monitor.join(timeout=1)
    child_usage_end = resource.getrusage(resource.RUSAGE_CHILDREN)
    size_before_checkpoint = _db_size(db_path)
    connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    connection.close()
    writer_io_end = _process_io(os.getpid())
    elapsed_s = time.monotonic() - start_mono
    if process.returncode != 0:
        errors.append(f"collector exited {process.returncode}")
    if seen != args.samples:
        errors.append(f"expected {args.samples} samples, got {seen}")
    return {
        "schema": 1,
        "collector": str(args.collector.resolve()),
        "mode": args.mode,
        "samples_requested": args.samples,
        "samples_received": seen,
        "interval_ms": args.interval_ms,
        "started_at_epoch_s": start_wall,
        "elapsed_s": elapsed_s,
        "collector_cpu": {
            "user_s": child_usage_end.ru_utime - child_usage_start.ru_utime,
            "system_s": child_usage_end.ru_stime - child_usage_start.ru_stime,
        },
        "collector_cpu_polled": {"user_s": peaks["cpu_user_s"], "system_s": peaks["cpu_system_s"]},
        "collector_peak_rss_bytes": peaks["rss_bytes"],
        "collector_io_peak": peaks["io"],
        "writer_cpu_s": sqlite_cpu_s,
        "harness_cpu_s": time.process_time() - writer_cpu_start,
        "collector_rusage_blocks": {
            "input": child_usage_end.ru_inblock - child_usage_start.ru_inblock,
            "output": child_usage_end.ru_oublock - child_usage_start.ru_oublock,
        },
        "sample_duration_ns": durations_ns,
        "commit_wall_ns": commit_wall_ns,
        "received_monotonic_ns": received_monotonic_ns,
        "collector_cpu_at_sample": collector_cpu_at_sample,
        "processes_seen": process_counts,
        "process_rows": process_rows,
        "process_io_available": process_io_available,
        "sample_source_errors": sample_source_errors,
        "host_availability": host_availability,
        "writer_io_delta": {
            key: writer_io_end.get(key, 0) - writer_io_start.get(key, 0)
            for key in writer_io_start
        },
        "output_bytes": output_bytes,
        "sqlite_bytes_before_checkpoint": size_before_checkpoint,
        "sqlite_bytes_after_checkpoint": _db_size(db_path),
        "python": platform.python_version(),
        "kernel": platform.release(),
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collector", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--mode", choices=("baseline", "detail"), required=True)
    parser.add_argument("--samples", type=int, default=10)
    parser.add_argument("--interval-ms", type=int, default=1000)
    parser.add_argument("--service-cgroup", type=Path)
    args = parser.parse_args()
    if args.samples < 1 or args.interval_ms < 1:
        parser.error("samples and interval-ms must be positive")
    result = _run(args)
    (args.output_dir / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, separators=(",", ":")))
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
