#!/usr/bin/env python3
"""Run the finite host-collector comparison in balanced sequential order."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import psutil


COLLECTORS = ("python", "go", "rust")
WORKLOADS = (("baseline", 6, 5000), ("detail", 10, 1000))


def _p95(values: Iterable[int]) -> int | None:
    ordered = sorted(values)
    if not ordered:
        return None
    rank = 0.95 * (len(ordered) - 1)
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    return round(ordered[low] + (ordered[high] - ordered[low]) * (rank - low))


def _steady_cpu_pct(run: dict[str, Any]) -> float | None:
    snapshots = run["collector_cpu_at_sample"]
    times = run["received_monotonic_ns"]
    valid = [index for index, snapshot in enumerate(snapshots) if snapshot is not None]
    if len(valid) < 2:
        return None
    first, last = valid[0], valid[-1]
    start = snapshots[first]
    end = snapshots[last]
    assert start is not None and end is not None
    elapsed_s = (times[last] - times[first]) / 1e9
    if elapsed_s <= 0:
        return None
    cpu_s = end["user_s"] + end["system_s"] - start["user_s"] - start["system_s"]
    return 100 * cpu_s / elapsed_s


def _sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _aggregate(runs: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for run in runs:
        key = f"{run['collector_name']}:{run['mode']}"
        grouped.setdefault(key, []).append(run)
    result: dict[str, Any] = {}
    for key, group in grouped.items():
        cpu_pct = [
            100 * (run["collector_cpu"]["user_s"] + run["collector_cpu"]["system_s"])
            / run["elapsed_s"]
            for run in group
        ]
        warm_cpu_pct = [_steady_cpu_pct(run) for run in group]
        rss = [run["collector_peak_rss_bytes"] for run in group]
        durations = [duration for run in group for duration in run["sample_duration_ns"]]
        bytes_per_sample = [run["output_bytes"] / run["samples_received"] for run in group]
        result[key] = {
            "runs": len(group),
            "cpu_one_core_pct_median": statistics.median(cpu_pct),
            "cpu_one_core_pct_range": [min(cpu_pct), max(cpu_pct)],
            "warm_cpu_one_core_pct_median": statistics.median(
                value for value in warm_cpu_pct if value is not None
            ),
            "peak_rss_bytes_median": statistics.median(rss),
            "sample_duration_p95_ns": _p95(durations),
            "sample_plus_commit_p95_ns": _p95(
                duration + commit
                for run in group
                for duration, commit in zip(run["sample_duration_ns"], run["commit_wall_ns"], strict=True)
            ),
            "output_bytes_per_sample_median": statistics.median(bytes_per_sample),
            "collector_rchar_median": statistics.median(
                run["collector_io_peak"].get("rchar", 0) for run in group
            ),
            "collector_physical_write_bytes_median": statistics.median(
                run["collector_io_peak"].get("write_bytes", 0) for run in group
            ),
            "writer_physical_write_bytes_median": statistics.median(
                run["writer_io_delta"].get("write_bytes", 0) for run in group
            ),
            "process_io_available_fraction": statistics.median(
                sum(run["process_io_available"]) / sum(run["process_rows"]) for run in group
            ),
            "sqlite_before_checkpoint_bytes_median": statistics.median(
                sum(run["sqlite_bytes_before_checkpoint"].values()) for run in group
            ),
            "processes_seen_range": [
                min(count for run in group for count in run["processes_seen"]),
                max(count for run in group for count in run["processes_seen"]),
            ],
            "errors": [error for run in group for error in run["errors"]],
            "source_errors": sorted(
                {
                    f"{error['source']}:{error['code']}"
                    for run in group
                    for sample_errors in run["sample_source_errors"]
                    for error in sample_errors
                }
            ),
        }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--service-cgroup", type=Path)
    args = parser.parse_args()
    if args.rounds < 1:
        parser.error("rounds must be positive")

    project_root = Path(__file__).resolve().parent.parent
    output_dir = args.output_dir.resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        parser.error("output directory must be empty")
    output_dir.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []
    for round_index in range(args.rounds):
        order = COLLECTORS[round_index % 3 :] + COLLECTORS[: round_index % 3]
        for mode, samples, interval_ms in WORKLOADS:
            for name in order:
                run_dir = output_dir / f"round-{round_index + 1}" / mode / name
                command = [
                    sys.executable,
                    str(project_root / "scripts/benchmark_system_monitor.py"),
                    "--collector",
                    str(project_root / "experiments/system-monitor" / name / "run.sh"),
                    "--output-dir",
                    str(run_dir),
                    "--mode",
                    mode,
                    "--samples",
                    str(samples),
                    "--interval-ms",
                    str(interval_ms),
                ]
                if args.service_cgroup:
                    command.extend(("--service-cgroup", str(args.service_cgroup)))
                print(f"RUN round={round_index + 1} mode={mode} collector={name}", flush=True)
                completed = subprocess.run(command, cwd=project_root, capture_output=True, text=True)
                if completed.returncode != 0:
                    print(completed.stderr or completed.stdout, file=sys.stderr)
                    return completed.returncode
                summary = json.loads((run_dir / "summary.json").read_text())
                summary["collector_name"] = name
                summary["round"] = round_index + 1
                results.append(summary)
                print(
                    f"DONE mode={mode} collector={name} samples={summary['samples_received']} "
                    f"cpu_s={sum(summary['collector_cpu'].values()):.3f} "
                    f"rss_mib={summary['collector_peak_rss_bytes'] / 1048576:.1f}",
                    flush=True,
                )

    identity_files = {
        "python_source": project_root / "experiments/system-monitor/python/collector.py",
        "go_binary": project_root / "experiments/system-monitor/go/.build/collector",
        "go_manifest": project_root / "experiments/system-monitor/go/go.sum",
        "rust_binary": project_root / "experiments/system-monitor/rust/target/release/summitflow-host-collector-rust",
        "rust_manifest": project_root / "experiments/system-monitor/rust/Cargo.lock",
    }
    report = {
        "schema": 1,
        "identity_sha256": {name: _sha256(path) for name, path in identity_files.items()},
        "toolchain": {
            "python": sys.version.split()[0],
            "psutil": psutil.__version__,
            "go": subprocess.check_output(["go", "version"], text=True).strip(),
            "rustc": subprocess.check_output(["rustc", "--version"], text=True).strip(),
        },
        "runs": results,
        "aggregate": _aggregate(results),
    }
    (output_dir / "comparison.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report["aggregate"], separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
