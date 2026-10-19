"""CPU, memory, and port telemetry collection."""

from __future__ import annotations

import asyncio
import os
import re
import time
from typing import Any

# Late-bound access to helpers — ensures mocks at helpers.* take effect at runtime.
from . import _process_execution as _pe
from . import helpers as _h
from ._process_execution import _run_command  # never mocked at helpers.*
from .constants import runtime_service_definitions
from .models import RuntimeServiceMetrics

__all__ = [
    "_listener_pids",
    "_ps_metrics",
    "_runtime_metrics",
    "_signal_port_listeners",
    "_systemd_service_metric",
    "_unit_cgroup_counters",
]

_FIRST_SAMPLE_DELAY_SECONDS = 0.5
# unit -> (monotonic_ns, CPUUsageNSec) from the previous reading, shared by the
# sampler and live GETs so CPU% is the cgroup's usage over the elapsed interval.
_cpu_samples: dict[str, tuple[int, int]] = {}


def _monotonic_ns() -> int:
    return time.monotonic_ns()


def _systemd_int(value: str | None) -> int | None:
    """Parse systemd numeric properties; '[not set]' and UINT64_MAX mean unavailable."""
    if not value or not value.isdigit():
        return None
    number = int(value)
    return None if number >= 2**64 - 1 else number


def _total_memory_bytes() -> int | None:
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (ValueError, OSError):
        return None


async def _unit_cgroup_counters(unit: str) -> tuple[str, int | None, int | None]:
    """Return (ActiveState, CPUUsageNSec, MemoryCurrent) for the unit's cgroup."""
    run = _pe._run_systemctl_system if _pe._is_system_unit(unit) else _h._run_systemctl_user
    stdout, _stderr, rc = await run(
        "show", unit, "-p", "ActiveState", "-p", "CPUUsageNSec", "-p", "MemoryCurrent",
    )
    if rc != 0:
        return "unknown", None, None
    data = _h._parse_systemctl_show(stdout)
    return (
        data.get("ActiveState", "unknown"),
        _systemd_int(data.get("CPUUsageNSec")),
        _systemd_int(data.get("MemoryCurrent")),
    )


def _cpu_percent_since_last(unit: str, now_ns: int, cpu_ns: int) -> float | None:
    previous = _cpu_samples.get(unit)
    _cpu_samples[unit] = (now_ns, cpu_ns)
    if previous is None:
        return None
    elapsed_ns = now_ns - previous[0]
    used_ns = cpu_ns - previous[1]
    if elapsed_ns <= 0 or used_ns < 0:  # restarted unit resets its counter
        return None
    return used_ns / elapsed_ns * 100


async def _ps_metrics(pid: int) -> RuntimeServiceMetrics | None:
    stdout, _stderr, rc = await _run_command(
        "ps", "-p", str(pid), "-o", "pid=,%cpu=,%mem=,rss=",
    )
    if rc != 0 or not stdout.strip():
        return None
    parts = stdout.strip().split()
    if len(parts) != 4:
        return None
    _pid, cpu, mem_percent, rss_kib = parts
    try:
        rss_bytes = int(rss_kib) * 1024
    except ValueError:
        rss_bytes = 0
    return RuntimeServiceMetrics(
        name=str(pid),
        service="",
        cpu_percent=f"{cpu}%",
        mem_usage=_h._format_bytes(rss_bytes),
        mem_percent=f"{mem_percent}%",
        net_io="n/a",
        block_io="n/a",
    )


async def _listener_pids(port: str) -> list[int]:
    stdout, _stderr, rc = await _run_command("ss", "-ltnp", f"( sport = :{port} )")
    if rc != 0 or not stdout.strip():
        return []
    return sorted({int(match) for match in re.findall(r"pid=(\d+)", stdout)})


async def _signal_port_listeners(port: str, *, signal: int) -> None:
    """Send a signal to all processes listening on the given port."""
    for pid in await _listener_pids(port):
        try:
            os.kill(pid, signal)
        except ProcessLookupError:
            continue


async def _systemd_service_metric(svc: dict[str, Any]) -> RuntimeServiceMetrics | None:
    """CPU/memory for the whole unit cgroup (all processes), not the main PID."""
    unit = svc["unit"]
    active_state, cpu_ns, memory_bytes = await _unit_cgroup_counters(unit)
    if active_state != "active" or (cpu_ns is None and memory_bytes is None):
        _cpu_samples.pop(unit, None)
        return None

    cpu_percent: float | None = None
    if cpu_ns is not None:
        cpu_percent = _cpu_percent_since_last(unit, _monotonic_ns(), cpu_ns)
        if cpu_percent is None:
            # First sight of this unit: take a short second reading for a real rate.
            await asyncio.sleep(_FIRST_SAMPLE_DELAY_SECONDS)
            _state, cpu_ns_again, memory_again = await _unit_cgroup_counters(unit)
            if cpu_ns_again is not None:
                cpu_percent = _cpu_percent_since_last(unit, _monotonic_ns(), cpu_ns_again)
            memory_bytes = memory_again if memory_again is not None else memory_bytes

    total_memory = _total_memory_bytes()
    mem_percent = (
        f"{memory_bytes / total_memory * 100:.2f}%"
        if memory_bytes is not None and total_memory
        else "n/a"
    )
    return RuntimeServiceMetrics(
        name=unit,
        service=svc["service"],
        cpu_percent=f"{cpu_percent:.2f}%" if cpu_percent is not None else "n/a",
        mem_usage=_h._format_bytes(memory_bytes) if memory_bytes is not None else "n/a",
        mem_percent=mem_percent,
        net_io="n/a",
        block_io="n/a",
    )


async def _runtime_metrics() -> list[RuntimeServiceMetrics]:
    """Metrics for systemd services; docker stack containers are not inspected."""
    systemd_metrics = await asyncio.gather(
        *[_systemd_service_metric(svc) for svc in runtime_service_definitions() if svc["manager"] == "systemd"]
    )
    return [m for m in systemd_metrics if m is not None]
