"""CPU, memory, and port telemetry collection."""

from __future__ import annotations

import asyncio
import os
import re
from typing import Any

# Late-bound access to helpers — ensures mocks at helpers.* take effect at runtime.
from . import helpers as _h
from ._process_execution import _run_command  # never mocked at helpers.*
from .constants import _RUNTIME_SERVICE_DEFS
from .models import RuntimeServiceMetrics

__all__ = [
    "_collect_docker_metrics",
    "_listener_pids",
    "_ps_metrics",
    "_runtime_metrics",
    "_signal_port_listeners",
    "_systemd_service_metric",
]


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
    unit_state = await _h._systemd_unit_state(svc["unit"])
    main_pid_raw = unit_state.get("MainPID", "0")
    try:
        main_pid = int(main_pid_raw)
    except ValueError:
        return None
    if main_pid <= 0:
        return None
    metric = await _ps_metrics(main_pid)
    if metric is None:
        return None
    return RuntimeServiceMetrics(
        name=svc["unit"],
        service=svc["service"],
        cpu_percent=metric.cpu_percent,
        mem_usage=metric.mem_usage,
        mem_percent=metric.mem_percent,
        net_io=metric.net_io,
        block_io=metric.block_io,
    )


async def _collect_docker_metrics(
    docker_containers: dict[str, dict[str, Any]],
) -> list[RuntimeServiceMetrics]:
    """Collect metrics for all running Docker containers."""
    docker_container_names = {
        container.get("Names", ""): service
        for service, container in docker_containers.items()
    }

    id_stdout, _id_stderr, rc = await _h._run_docker("docker", "ps", "-q", *_h._project_filter())
    if rc != 0 or not id_stdout.strip():
        return []

    container_ids = id_stdout.strip().split()
    stdout, _stderr, rc = await _h._run_docker(
        "docker", "stats", "--no-stream", "--format", "json", *container_ids,
    )
    if rc != 0 or not stdout.strip():
        return []

    return [
        RuntimeServiceMetrics(
            name=c.get("Name", ""),
            service=docker_container_names.get(c.get("Name", ""), c.get("Name", "")),
            cpu_percent=c.get("CPUPerc", "0%"),
            mem_usage=c.get("MemUsage", "0B / 0B"),
            mem_percent=c.get("MemPerc", "0%"),
            net_io=c.get("NetIO", "0B / 0B"),
            block_io=c.get("BlockIO", "0B / 0B"),
        )
        for c in _h._parse_json_lines(stdout)
    ]


async def _runtime_metrics() -> list[RuntimeServiceMetrics]:
    docker_containers = await _h._docker_container_map(all_containers=False)
    docker_metrics = await _collect_docker_metrics(docker_containers)

    systemd_metrics = await asyncio.gather(
        *[_systemd_service_metric(svc) for svc in _RUNTIME_SERVICE_DEFS if svc["manager"] == "systemd"]
    )

    return docker_metrics + [m for m in systemd_metrics if m is not None]
