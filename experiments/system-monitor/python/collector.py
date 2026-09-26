#!/usr/bin/env python3
"""Finite Linux host observation fixture. JSON lines are the only stdout output."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import sys
import time

import psutil

TICKS = os.sysconf("SC_CLK_TCK")
CGROUP_ROOT = Path("/sys/fs/cgroup")


def read_text(path: Path) -> str:
    return path.read_text(encoding="ascii")


def error_code(exc: Exception) -> str:
    if isinstance(exc, (PermissionError, psutil.AccessDenied)):
        return "permission_denied"
    if isinstance(exc, (FileNotFoundError, ProcessLookupError, psutil.NoSuchProcess, psutil.ZombieProcess)):
        return "missing"
    if isinstance(exc, (ValueError, IndexError, KeyError)):
        return "invalid"
    return "io_error"


def attempt(source: str, fn, errors: list[dict], default=None):
    try:
        return fn()
    except (OSError, ValueError, IndexError, KeyError, psutil.Error) as exc:
        errors.append({"source": source, "code": error_code(exc)})
        return default


def cpu_counts() -> tuple[int, int]:
    fields = read_text(Path("/proc/stat")).splitlines()[0].split()
    if fields[0] != "cpu" or len(fields) < 5:
        raise ValueError("invalid aggregate CPU line")
    values = [int(value) for value in fields[1:]]
    return sum(values), values[3] + (values[4] if len(values) > 4 else 0)


def psi_avg10(kind: str) -> float:
    some = next(line for line in read_text(Path(f"/proc/pressure/{kind}")).splitlines() if line.startswith("some "))
    return float(next(item.split("=", 1)[1] for item in some.split()[1:] if item.startswith("avg10=")))


def net_bytes() -> tuple[int, int]:
    rx = tx = 0
    for line in read_text(Path("/proc/net/dev")).splitlines()[2:]:
        name, values = line.split(":", 1)
        if name.strip() == "lo":
            continue
        columns = values.split()
        rx += int(columns[0])
        tx += int(columns[8])
    return rx, tx


def disk_bytes() -> tuple[int, int]:
    devices = {path.name for path in Path("/sys/block").iterdir() if not path.name.startswith(("loop", "ram"))}
    read = write = 0
    for line in read_text(Path("/proc/diskstats")).splitlines():
        columns = line.split()
        if columns[2] in devices:
            read += int(columns[5]) * 512
            write += int(columns[9]) * 512
    return read, write


def host_sample(previous_cpu: tuple[int, int] | None, errors: list[dict]) -> tuple[dict, tuple[int, int] | None]:
    cpu = attempt("/proc/stat", cpu_counts, errors)
    busy = None
    if cpu is not None and previous_cpu is not None:
        total = cpu[0] - previous_cpu[0]
        idle = cpu[1] - previous_cpu[1]
        if total > 0 and 0 <= idle <= total:
            busy = max(0.0, min(100.0, 100.0 * (total - idle) / total))
        else:
            errors.append({"source": "/proc/stat", "code": "invalid_delta"})
    memory = attempt("memory", psutil.virtual_memory, errors)
    swap = attempt("swap", psutil.swap_memory, errors)
    disk = attempt("root_filesystem", lambda: psutil.disk_usage("/"), errors)
    net = attempt("/proc/net/dev", net_bytes, errors)
    disk_io = attempt("/proc/diskstats", disk_bytes, errors)
    host = {
        "cpu_busy_pct": busy,
        "memory_total_bytes": memory.total if memory else None,
        "memory_available_bytes": memory.available if memory else None,
        "swap_used_bytes": swap.used if swap else None,
        "disk_total_bytes": disk.total if disk else None,
        "disk_free_bytes": disk.free if disk else None,
        "cpu_some_avg10_pct": attempt("/proc/pressure/cpu", lambda: psi_avg10("cpu"), errors),
        "memory_some_avg10_pct": attempt("/proc/pressure/memory", lambda: psi_avg10("memory"), errors),
        "io_some_avg10_pct": attempt("/proc/pressure/io", lambda: psi_avg10("io"), errors),
        "net_rx_bytes": net[0] if net else None,
        "net_tx_bytes": net[1] if net else None,
        "disk_read_bytes": disk_io[0] if disk_io else None,
        "disk_write_bytes": disk_io[1] if disk_io else None,
    }
    return host, cpu


def process_stat(pid: int) -> tuple[int, str, int, int]:
    value = read_text(Path(f"/proc/{pid}/stat"))
    end = value.rfind(")")
    if end < 0:
        raise ValueError("invalid process stat")
    fields = value[end + 2:].split()
    return int(fields[19]), value[value.find("(") + 1:end], int(fields[11]), int(fields[12])


def process_sample() -> tuple[list[dict], int, int, int, int]:
    rows = []
    denied = exited = unavailable = 0
    pids = psutil.pids()
    for pid in pids:
        try:
            start, name, user, system = process_stat(pid)
            proc = psutil.Process(pid)
            field_failures = []
            try:
                rss = proc.memory_info().rss
            except (OSError, psutil.Error) as exc:
                rss = None
                field_failures.append(error_code(exc))
            try:
                io = proc.io_counters()
                read_bytes, write_bytes = io.read_bytes, io.write_bytes
            except (OSError, psutil.Error) as exc:
                read_bytes = write_bytes = None
                field_failures.append(error_code(exc))
            # A reused PID cannot combine counters from two different processes.
            if process_stat(pid)[0] != start:
                exited += 1
                continue
            if "permission_denied" in field_failures:
                denied += 1
            elif field_failures:
                unavailable += 1
            rows.append({
                "pid": pid, "start_ticks": start, "name": name,
                "cpu_user_ns": user * 1_000_000_000 // TICKS,
                "cpu_system_ns": system * 1_000_000_000 // TICKS,
                "rss_bytes": rss, "read_bytes": read_bytes,
                "write_bytes": write_bytes,
            })
        except (OSError, ValueError, IndexError, psutil.Error) as exc:
            if error_code(exc) == "permission_denied":
                denied += 1
            elif error_code(exc) == "missing":
                exited += 1
            else:
                unavailable += 1
    return rows, len(pids), denied, exited, unavailable


def service_sample(path: Path, errors: list[dict]) -> dict:
    def key_value(file: str, key: str) -> int:
        return int(next(line.split()[1] for line in read_text(path / file).splitlines() if line.split()[0] == key))

    def io_values() -> tuple[int, int]:
        read = write = 0
        for line in read_text(path / "io.stat").splitlines():
            values = dict(token.split("=", 1) for token in line.split()[1:])
            read += int(values["rbytes"])
            write += int(values["wbytes"])
        return read, write

    io = attempt("cgroup2/io.stat", io_values, errors)
    return {
        "source": "cgroup2",
        "cpu_usage_usec": attempt("cgroup2/cpu.stat", lambda: key_value("cpu.stat", "usage_usec"), errors),
        "memory_current_bytes": attempt("cgroup2/memory.current", lambda: int(read_text(path / "memory.current").strip()), errors),
        "io_read_bytes": io[0] if io else None,
        "io_write_bytes": io[1] if io else None,
    }


def baseline_rows(rows: list[dict], previous: dict[tuple[int, int], dict] | None) -> list[dict]:
    leaders: dict[tuple[int, int], set[str]] = {}

    def add_top(reason: str, candidates: list[dict], value):
        for row in sorted(candidates, key=lambda row: (-value(row), row["pid"], row["start_ticks"]))[:10]:
            leaders.setdefault((row["pid"], row["start_ticks"]), set()).add(reason)

    add_top("rss", [row for row in rows if row["rss_bytes"] is not None], lambda row: row["rss_bytes"])
    if previous is not None:
        eligible = [row for row in rows if (row["pid"], row["start_ticks"]) in previous]
        add_top("cpu", eligible, lambda row: max(0, row["cpu_user_ns"] + row["cpu_system_ns"] - previous[(row["pid"], row["start_ticks"])]["cpu_user_ns"] - previous[(row["pid"], row["start_ticks"])]["cpu_system_ns"]))
        io_eligible = [row for row in eligible if row["read_bytes"] is not None and row["write_bytes"] is not None and previous[(row["pid"], row["start_ticks"])]["read_bytes"] is not None and previous[(row["pid"], row["start_ticks"])]["write_bytes"] is not None]
        add_top("io", io_eligible, lambda row: max(0, row["read_bytes"] + row["write_bytes"] - previous[(row["pid"], row["start_ticks"])]["read_bytes"] - previous[(row["pid"], row["start_ticks"])]["write_bytes"]))
    return [{**row, "leader_reasons": sorted(leaders[(row["pid"], row["start_ticks"])])} for row in sorted(rows, key=lambda row: (row["pid"], row["start_ticks"])) if (row["pid"], row["start_ticks"]) in leaders]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("baseline", "detail"), required=True)
    parser.add_argument("--samples", type=int, required=True)
    parser.add_argument("--interval-ms", type=int)
    parser.add_argument("--service-cgroup", type=Path)
    args = parser.parse_args()
    if args.samples < 1 or (args.interval_ms is not None and args.interval_ms < 1):
        parser.error("samples and interval-ms must be positive")
    interval_ns = (args.interval_ms if args.interval_ms is not None else (5000 if args.mode == "baseline" else 1000)) * 1_000_000
    service_path = None
    if args.service_cgroup is not None:
        service_path = args.service_cgroup if args.service_cgroup.is_absolute() else CGROUP_ROOT / args.service_cgroup
        if not service_path.resolve().is_relative_to(CGROUP_ROOT):
            parser.error("service-cgroup must be within /sys/fs/cgroup")
    previous_time = None
    previous_cpu = None
    previous_processes = None
    next_deadline = time.monotonic_ns()
    for index in range(args.samples):
        remaining = next_deadline - time.monotonic_ns()
        if remaining > 0:
            time.sleep(remaining / 1_000_000_000)
        started = time.monotonic_ns()
        errors: list[dict] = []
        host, previous_cpu = host_sample(previous_cpu, errors)
        try:
            rows, seen, denied, exited, unavailable = process_sample()
        except (OSError, psutil.Error) as exc:
            errors.append({"source": "/proc", "code": error_code(exc)})
            rows, seen, denied, exited, unavailable = [], 0, 0, 0, 0
        service = service_sample(service_path, errors) if service_path else None
        selected = baseline_rows(rows, previous_processes) if args.mode == "baseline" else [{**row, "leader_reasons": []} for row in rows]
        previous_processes = {(row["pid"], row["start_ticks"]): row for row in rows}
        output = {
            "schema": 1,
            "sampled_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z"),
            "elapsed_ns": None if previous_time is None else started - previous_time,
            "mode": args.mode, "provider": "python-psutil", "duration_ns": time.monotonic_ns() - started,
            "host": host, "service": service, "processes": selected,
            "processes_seen": seen, "processes_permission_denied": denied,
            "processes_exited": exited, "processes_unavailable": unavailable,
            "errors": errors,
        }
        print(json.dumps(output, separators=(",", ":")), flush=True)
        previous_time = started
        next_deadline += interval_ns
    return 0


if __name__ == "__main__":
    sys.exit(main())
