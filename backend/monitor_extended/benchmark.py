"""Opt-in, short CPU and fixed-source cached disk-read probes."""
from __future__ import annotations

import hashlib
import os
import stat
import time
from pathlib import Path

from monitor_observe.common import ObserveQueryError, availability, base, error, item, limits, pack

PROJECT_IDENTITY = Path(__file__).resolve().parents[2] / "project.identity.json"
MAX_DURATION = 3.0
MAX_WORK_BYTES = 32 * 1024 * 1024
CHUNK = b"SummitFlow bounded CPU diagnostic\n" * 1024


def run_benchmark(kind: str, *, duration_seconds: float = 1.0,
                  max_bytes: int = 4096) -> dict:
    """Measure local self-cost; disk reads a fixed file and is cache affected.

    The CPU probe hashes a fixed in-memory block. The disk probe repeatedly
    reads only the checked-in project identity (no writes or arbitrary target).
    GPU and network report unsupported rather than fabricated measurements.
    """
    limits(1, max_bytes)
    if not isinstance(kind, str) or kind not in {"cpu", "disk", "gpu", "network"}:
        raise ObserveQueryError("kind must be cpu, disk, gpu, or network")
    if isinstance(duration_seconds, bool) or not isinstance(duration_seconds, (int, float)) or not 0 < duration_seconds <= MAX_DURATION:
        raise ObserveQueryError(f"duration_seconds must be >0..{MAX_DURATION}")
    payload = base("benchmark", {"benchmark": kind, "duration_seconds": duration_seconds})
    if kind in {"gpu", "network"}:
        payload["coverage"] = {"availability": "unsupported", "reason": "no configured bounded provider"}
        payload["errors"].append(error("unsupported", kind))
        return pack(payload, [], limit=1, max_bytes=max_bytes)
    deadline = time.monotonic() + duration_seconds
    cpu_start = time.process_time()
    wall_start = time.monotonic()
    processed = 0
    iterations = 0
    try:
        if kind == "cpu":
            while processed + len(CHUNK) <= MAX_WORK_BYTES and time.monotonic() < deadline:
                hashlib.sha256(CHUNK).digest()
                processed += len(CHUNK)
                iterations += 1
            provider = "hashlib.sha256"
            source = "in_memory_fixed_block"
        else:
            descriptor = os.open(PROJECT_IDENTITY, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                info = os.fstat(descriptor)
                if not stat.S_ISREG(info.st_mode) or info.st_size > 64 * 1024:
                    raise ObserveQueryError("fixed disk source unavailable or too large")
                while processed < MAX_WORK_BYTES and time.monotonic() < deadline:
                    block = os.read(descriptor, min(64 * 1024, MAX_WORK_BYTES - processed))
                    if not block:
                        os.lseek(descriptor, 0, os.SEEK_SET)
                        block = os.read(descriptor, min(64 * 1024, MAX_WORK_BYTES - processed))
                        if not block:
                            break
                    processed += len(block)
                    iterations += 1
            finally:
                os.close(descriptor)
            provider = "os.read"
            source = "project.identity.json"
    except OSError as exc:
        code = availability(exc)
        payload["coverage"] = {"availability": code}
        payload["errors"].append(error(code, "fixed_benchmark_source"))
        return pack(payload, [], limit=1, max_bytes=max_bytes)
    elapsed = max(time.monotonic() - wall_start, 1e-9)
    cpu_seconds = max(0.0, time.process_time() - cpu_start)
    payload["coverage"] = {"availability": "ok", "completed": True,
                           "work_cap_bytes": MAX_WORK_BYTES,
                           "duration_cap_seconds": MAX_DURATION,
                           "cache_affected": kind == "disk",
                           "measurement": "cached_file_read_probe" if kind == "disk" else "in_memory_hash_probe",
                           "physical_disk_throughput": "not_measured"}
    value = {"bytes_processed": processed, "iterations": iterations,
             "elapsed_seconds": round(elapsed, 6), "process_cpu_seconds": round(cpu_seconds, 6),
             "bytes_per_second": round(processed / elapsed, 2),
             "cpu_cost_pct_one_core": round(100 * cpu_seconds / elapsed, 2),
             "source": source, "workload": "sha256_fixed_block" if kind == "cpu" else "repeated_cached_file_read"}
    return pack(payload, [item(source, provider, "ok", value, unit="bytes/s")],
                limit=1, max_bytes=max_bytes)
