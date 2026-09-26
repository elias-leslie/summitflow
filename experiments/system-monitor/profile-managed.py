"""Profile the installed SummitFlow collector cgroup and committed store.

Run only after a managed rebuild. This script never changes service state; its
only collector control is one expiring detail lease, which it ends in finally.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import socket
import statistics
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path


def command(*args: str) -> str:
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout.strip()


def cgroup_path() -> Path:
    relative = command("systemctl", "--user", "show", "-P", "ControlGroup", "summitflow-host-monitor.service")
    path = (Path("/sys/fs/cgroup") / relative.lstrip("/")).resolve()
    if not path.is_relative_to(Path("/sys/fs/cgroup")) or not path.is_dir():
        raise RuntimeError("managed monitor cgroup is unavailable")
    return path


def service_pid() -> int:
    pid = int(command("systemctl", "--user", "show", "-P", "MainPID", "summitflow-host-monitor.service"))
    if pid <= 0:
        raise RuntimeError("managed monitor process is unavailable")
    return pid


def cpu_usec(root: Path) -> int:
    for line in (root / "cpu.stat").read_text().splitlines():
        key, value = line.split()
        if key == "usage_usec":
            return int(value)
    raise RuntimeError("cgroup CPU usage is unavailable")


def io_bytes(root: Path, pid: int) -> tuple[int, int]:
    source = root / "io.stat"
    if not source.exists():
        values = dict(line.split(":", 1) for line in Path(f"/proc/{pid}/io").read_text().splitlines())
        return int(values["read_bytes"]), int(values["write_bytes"])
    read = write = 0
    for line in source.read_text().splitlines():
        for entry in line.split()[1:]:
            key, _, value = entry.partition("=")
            if key == "rbytes":
                read += int(value)
            elif key == "wbytes":
                write += int(value)
    return read, write


def store_bytes(root: Path) -> int:
    return sum(path.stat().st_size for path in (root / "monitor.sqlite3", root / "monitor.sqlite3-wal",
                                                root / "monitor.sqlite3-shm") if path.exists())


def collector_latency(state: Path) -> tuple[int, int | None]:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as channel:
        channel.settimeout(2)
        channel.connect(str(state / "control.sock"))
        channel.sendall(b'{"command":"status"}\n')
        with channel.makefile("rb") as stream:
            status = json.loads(stream.readline(262_144))
    if not status.get("ok"):
        raise RuntimeError("collector status unavailable")
    total = status.get("sample_commit_total")
    if type(total) is not int or total < 0:
        raise RuntimeError("collector status lacks monotonic sample_commit_total; rebuild the collector")
    return total, status.get("sample_commit_last_ns")


def snapshot(cgroup: Path, state: Path, pid: int) -> dict[str, float | int]:
    read, write = io_bytes(cgroup, pid)
    commit_count, commit_last = collector_latency(state)
    return {"at": time.monotonic(), "cpu_usec": cpu_usec(cgroup),
            "memory_bytes": int((cgroup / "memory.current").read_text()),
            "io_read_bytes": read, "io_write_bytes": write, "store_bytes": store_bytes(state),
            "commit_count": commit_count, "commit_last_ns": commit_last or 0}


def measure(cgroup: Path, state: Path, pid: int, seconds: int) -> list[dict[str, float | int]]:
    observations = [snapshot(cgroup, state, pid)]
    deadline = observations[0]["at"] + seconds
    while time.monotonic() < deadline:
        time.sleep(min(1, max(0, deadline - time.monotonic())))
        observations.append(snapshot(cgroup, state, pid))
    return observations


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * p))]


def summarize(rows: list[dict[str, float | int]]) -> dict[str, float | int | None]:
    first, last = rows[0], rows[-1]
    seconds = float(last["at"] - first["at"])
    counts = [int(row["commit_count"]) for row in rows]
    if any(current < previous for previous, current in zip(counts, counts[1:])):
        raise RuntimeError("collector commit total reset during profile")
    commits = [int(row["commit_last_ns"]) / 1_000_000 for previous, row in zip(rows, rows[1:])
               if int(row["commit_count"]) > int(previous["commit_count"]) and row["commit_last_ns"]]
    return {"seconds": round(seconds, 3),
            "cpu_percent_one_core": round((int(last["cpu_usec"]) - int(first["cpu_usec"])) / (seconds * 10_000), 3),
            "memory_mib_median": round(statistics.median(int(row["memory_bytes"]) for row in rows) / 2**20, 3),
            "memory_mib_peak": round(max(int(row["memory_bytes"]) for row in rows) / 2**20, 3),
            "io_read_bytes": int(last["io_read_bytes"]) - int(first["io_read_bytes"]),
            "io_write_bytes": int(last["io_write_bytes"]) - int(first["io_write_bytes"]),
            "io_write_bytes_per_day_extrapolated": round((int(last["io_write_bytes"]) - int(first["io_write_bytes"])) / seconds * 86400),
            "store_bytes_delta": int(last["store_bytes"]) - int(first["store_bytes"]),
            "observed_sample_commits": counts[-1] - counts[0],
            "sample_plus_commit_latency_observations": len(commits),
            "sample_plus_commit_p95_ms": round(percentile(commits, .95), 3) if commits else None}


def committed_stats(state: Path, since: int) -> dict[str, float | int | None]:
    uri = f"file:{state / 'monitor.sqlite3'}?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        rows = conn.execute("SELECT mode,duration_ns FROM samples WHERE sampled_at_ns>=?", (since,)).fetchall()
    out: dict[str, float | int | None] = {}
    for mode in ("baseline", "detail"):
        values = [duration / 1_000_000 for kind, duration in rows if kind == mode]
        out[f"{mode}_rows_in_full_profile"] = len(values)
        out[f"{mode}_precommit_collection_p95_ms"] = round(percentile(values, .95), 3) if values else None
    return out


def query_latency() -> dict[str, float | None]:
    result: dict[str, float | None] = {}
    for name, args in (("status", ("status",)), ("processes", ("processes", "--limit", "10")),
                       ("series", ("series", "cpu_busy_pct", "--since", "15m", "--limit", "10"))):
        values = []
        for _ in range(20):
            started = time.monotonic()
            payload = json.loads(command("st", "monitor", *args))
            if payload.get("schema") != 1 or not isinstance(payload.get("items"), list):
                raise RuntimeError(f"{name} returned an invalid monitor response")
            values.append((time.monotonic() - started) * 1000)
        result[f"{name}_cli_p95_ms"] = round(percentile(values, .95), 3)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-seconds", type=int, default=60)
    parser.add_argument("--detail-seconds", type=int, default=30)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 10 <= args.baseline_seconds <= 600 or not 5 <= args.detail_seconds <= 300:
        parser.error("baseline must be 10..600 seconds and detail 5..300 seconds")
    cgroup = cgroup_path()
    pid = service_pid()
    state = Path.home() / ".local/state/summitflow/monitor"
    since = time.time_ns()
    baseline = measure(cgroup, state, pid, args.baseline_seconds)
    lease = json.loads(command("st", "monitor", "capture", "--ttl-seconds", str(min(300, args.detail_seconds + 5))))
    lease_id = lease.get("lease_id")
    if not lease.get("ok") or not isinstance(lease_id, str):
        raise RuntimeError("collector rejected detail lease")
    try:
        detail = measure(cgroup, state, pid, args.detail_seconds)
    finally:
        command("st", "monitor", "capture-end", lease_id)
    result = {"schema": 1, "measured_at": datetime.now(UTC).isoformat(),
              "unit": "summitflow-host-monitor.service",
              "io_source": "cgroup2/io.stat" if (cgroup / "io.stat").exists() else "proc/pid/io",
              "baseline": summarize(baseline),
              "detail": summarize(detail), "committed": committed_stats(state, since),
              "query": query_latency()}
    args.output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    args.output.chmod(0o600)
    print(json.dumps(result, separators=(",", ":")))


if __name__ == "__main__":
    main()
