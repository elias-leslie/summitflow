"""Read the independent, owner-local host monitor from st."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any

import typer

from monitor_control import MonitorControlError, control_request, enrich_status, monitor_state_dir
from monitor_extended import export_capture, query_disk_space, run_benchmark
from monitor_observe import (
    ObserveQueryError,
    query_apps,
    query_connections,
    query_drivers,
    query_logs,
    query_sensors,
    query_startup,
    query_system_info,
    query_users,
)
from monitor_reader import MonitorQueryError, MonitorReader

from ..lib.usage import usage

app = typer.Typer(help="Bounded local host telemetry and troubleshooting history.", no_args_is_help=True)
_RELATIVE = re.compile(r"^(\d+)([mhd])$")


def _state_dir() -> Path:
    return monitor_state_dir()


def _time(value: str | None) -> str | None:
    if value is None:
        return None
    match = _RELATIVE.fullmatch(value)
    if match:
        amount = int(match.group(1))
        unit = {"m": 60, "h": 3600, "d": 86400}[match.group(2)]
        return (datetime.now(UTC) - timedelta(seconds=amount * unit)).isoformat()
    return value


def _required_time(value: str | None) -> str:
    parsed = _time(value)
    if parsed is None:
        raise MonitorQueryError("UTC time is required")
    return parsed


def _emit(result: dict[str, Any], max_bytes: int) -> None:
    encoded = json.dumps(result, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    if len(encoded.encode()) > max_bytes:
        raise MonitorQueryError("response exceeds max_bytes")
    print(encoded)


def _failure(exc: MonitorQueryError, max_bytes: int) -> None:
    message = str(exc)
    code = "collector_stopped" if "store unavailable" in message else "query_error"
    result = {
        "schema": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "requested": {},
        "coverage": {"availability": code},
        "items": [],
        "next_cursor": None,
        "truncated": False,
        "errors": [{"code": code, "message": message[:200]}],
    }
    _emit(result, max(512, max_bytes))
    raise typer.Exit(1)


def _query(method: str, max_bytes: int, **kwargs: Any) -> None:
    try:
        reader = MonitorReader(_state_dir())
        result = getattr(reader, method)(max_bytes=max_bytes, **kwargs)
        if method == "status":
            result = enrich_status(result, max_bytes)
        _emit(result, max_bytes)
    except MonitorQueryError as exc:
        _failure(exc, max_bytes)


def _observe(query: Any, max_bytes: int, **kwargs: Any) -> None:
    try:
        _emit(query(max_bytes=max_bytes, **kwargs), max_bytes)
    except ObserveQueryError as exc:
        _failure(MonitorQueryError(str(exc)), max_bytes)


@app.command()
@usage(
    surface="st.monitor.status",
    cmd="st monitor status",
    when="inspect current host and managed-service health without PostgreSQL or backend availability",
    precautions=("read-only, owner-local monitor store", "freshness and source errors are explicit"),
    examples=("st monitor status", "st monitor status --max-bytes 8192"),
    task_types=("devops", "debugging"),
    tier="reference",
)
def status(max_bytes: Annotated[int, typer.Option("--max-bytes", min=512, max=65536)] = 4096) -> None:
    """Latest committed host and managed-service observation."""
    _query("status", max_bytes)


@app.command()
def series(
    metric: Annotated[str, typer.Argument(help="Whitelisted host or service metric")],
    entity: Annotated[str, typer.Option("--entity", help="host or managed service id")] = "host",
    since: Annotated[str | None, typer.Option("--since", help="UTC timestamp or 15m/6h/1d")] = None,
    until: Annotated[str | None, typer.Option("--until", help="UTC timestamp")] = None,
    step: Annotated[int, typer.Option("--step", min=5, max=3600)] = 60,
    limit: Annotated[int, typer.Option("--limit", min=1, max=100)] = 10,
    cursor: Annotated[str | None, typer.Option("--cursor")] = None,
    max_bytes: Annotated[int, typer.Option("--max-bytes", min=512, max=65536)] = 4096,
) -> None:
    """Bucketed timeline with gaps, coverage and source availability."""
    if cursor and (not since or _RELATIVE.fullmatch(since) or not until):
        _failure(MonitorQueryError("pagination requires absolute --since and --until from coverage"), max_bytes)
    _query("series", max_bytes, metric=metric, entity=entity, since=_time(since), until=_time(until),
           step=step, limit=limit, cursor=cursor)


@app.command()
def processes(
    at: Annotated[str | None, typer.Option("--at", help="UTC timestamp; defaults to latest")] = None,
    name: Annotated[str | None, typer.Option("--name")] = None,
    user: Annotated[str | None, typer.Option("--user")] = None,
    service: Annotated[str | None, typer.Option("--service")] = None,
    sort: Annotated[str, typer.Option("--sort", help="cpu, rss, io")] = "rss",
    limit: Annotated[int, typer.Option("--limit", min=1, max=100)] = 10,
    cursor: Annotated[str | None, typer.Option("--cursor")] = None,
    max_bytes: Annotated[int, typer.Option("--max-bytes", min=512, max=65536)] = 4096,
) -> None:
    """Process leaders or bounded detail at a specific sample."""
    _query("processes", max_bytes, at=_time(at), name=name, user=user, service=service,
           sort=sort, limit=limit, cursor=cursor)


@app.command()
def events(
    since: Annotated[str | None, typer.Option("--since", help="UTC timestamp or 15m/6h/1d")] = None,
    until: Annotated[str | None, typer.Option("--until", help="UTC timestamp")] = None,
    kind: Annotated[str | None, typer.Option("--kind")] = None,
    severity: Annotated[str | None, typer.Option("--severity")] = None,
    entity: Annotated[str | None, typer.Option("--entity")] = None,
    limit: Annotated[int, typer.Option("--limit", min=1, max=100)] = 10,
    cursor: Annotated[str | None, typer.Option("--cursor")] = None,
    max_bytes: Annotated[int, typer.Option("--max-bytes", min=512, max=65536)] = 4096,
) -> None:
    """Source, service, and capture events in a bounded time window."""
    if cursor and (not since or _RELATIVE.fullmatch(since) or not until):
        _failure(MonitorQueryError("pagination requires absolute --since and --until from coverage"), max_bytes)
    _query("events", max_bytes, since=_time(since), until=_time(until), kind=kind,
           severity=severity, entity=entity, limit=limit, cursor=cursor)


@app.command()
def capture(
    ttl_seconds: Annotated[int, typer.Option("--ttl-seconds", min=1, max=300)] = 30,
) -> None:
    """Start a short lived, all-process detail capture lease."""
    try:
        result = control_request("lease_start", ttl_seconds=ttl_seconds)
        if not result["ok"]:
            raise MonitorControlError(str(result.get("error", "capture rejected")))
        _emit(result, 4096)
    except MonitorControlError as exc:
        _failure(MonitorQueryError(str(exc)), 4096)


@app.command("capture-renew")
def capture_renew(
    lease_id: Annotated[str, typer.Argument()],
    ttl_seconds: Annotated[int, typer.Option("--ttl-seconds", min=1, max=300)] = 30,
) -> None:
    """Renew an existing detail lease."""
    try:
        result = control_request("lease_renew", lease_id=lease_id, ttl_seconds=ttl_seconds)
        if not result["ok"]:
            raise MonitorControlError(str(result.get("error", "lease renewal rejected")))
        _emit(result, 4096)
    except MonitorControlError as exc:
        _failure(MonitorQueryError(str(exc)), 4096)


@app.command("capture-end")
def capture_end(lease_id: Annotated[str, typer.Argument()]) -> None:
    """End a detail lease early."""
    try:
        result = control_request("lease_end", lease_id=lease_id)
        if not result["ok"]:
            raise MonitorControlError(str(result.get("error", "lease end rejected")))
        _emit(result, 4096)
    except MonitorControlError as exc:
        _failure(MonitorQueryError(str(exc)), 4096)


@app.command()
def logs(
    service: Annotated[str, typer.Argument(help="Managed service id or backend/frontend alias")],
    since: Annotated[str | None, typer.Option("--since", help="UTC timestamp or 15m/6h/1d")] = None,
    until: Annotated[str | None, typer.Option("--until", help="UTC timestamp")] = None,
    cursor: Annotated[str | None, typer.Option("--cursor", help="Opaque journal cursor")] = None,
    priority: Annotated[int | None, typer.Option("--priority", min=0, max=7)] = None,
    limit: Annotated[int, typer.Option("--limit", min=1, max=100)] = 10,
    max_bytes: Annotated[int, typer.Option("--max-bytes", min=512, max=65536)] = 4096,
) -> None:
    """Redacted, bounded journal entries for one managed service."""
    if cursor and (not since or _RELATIVE.fullmatch(since) or not until):
        _failure(MonitorQueryError("pagination requires absolute --since and --until from requested"), max_bytes)
    _observe(query_logs, max_bytes, service=service, since=_time(since), until=_time(until),
             cursor=cursor, priority=priority, limit=limit)


@app.command()
def sensors(
    limit: Annotated[int, typer.Option("--limit", min=1, max=100)] = 10,
    max_bytes: Annotated[int, typer.Option("--max-bytes", min=512, max=65536)] = 4096,
) -> None:
    """Available temperatures, fans, CPU frequencies and power readings."""
    _observe(query_sensors, max_bytes, limit=limit)


@app.command()
def connections(
    limit: Annotated[int, typer.Option("--limit", min=1, max=100)] = 10,
    show_addresses: Annotated[bool, typer.Option("--show-addresses", help="Include local and remote endpoints")] = False,
    include_process: Annotated[bool, typer.Option("--include-process", help="Attempt socket owner lookup")] = False,
    max_bytes: Annotated[int, typer.Option("--max-bytes", min=512, max=65536)] = 4096,
) -> None:
    """On-demand socket states, with endpoints redacted by default."""
    _observe(query_connections, max_bytes, limit=limit, include_addresses=show_addresses,
             include_process=include_process)


@app.command("system-info")
def system_info(max_bytes: Annotated[int, typer.Option("--max-bytes", min=512, max=65536)] = 4096) -> None:
    """Static OS and hardware information without serial numbers."""
    _observe(query_system_info, max_bytes)


@app.command()
def users(limit: Annotated[int, typer.Option("--limit", min=1, max=100)] = 10,
          max_bytes: Annotated[int, typer.Option("--max-bytes", min=512, max=65536)] = 4096) -> None:
    """Local account inventory; sessions are reported separately as unavailable."""
    _observe(query_users, max_bytes, limit=limit)


@app.command()
def startup(limit: Annotated[int, typer.Option("--limit", min=1, max=100)] = 10,
            max_bytes: Annotated[int, typer.Option("--max-bytes", min=512, max=65536)] = 4096) -> None:
    """Enabled user service inventory."""
    _observe(query_startup, max_bytes, limit=limit)


@app.command()
def apps(limit: Annotated[int, typer.Option("--limit", min=1, max=100)] = 10,
         max_bytes: Annotated[int, typer.Option("--max-bytes", min=512, max=65536)] = 4096) -> None:
    """Installed Debian packages, bounded and read-only."""
    _observe(query_apps, max_bytes, limit=limit)


@app.command()
def drivers(limit: Annotated[int, typer.Option("--limit", min=1, max=100)] = 10,
            max_bytes: Annotated[int, typer.Option("--max-bytes", min=512, max=65536)] = 4096) -> None:
    """Loaded kernel modules, with no driver control actions."""
    _observe(query_drivers, max_bytes, limit=limit)


@app.command("disk-space")
def disk_space(
    path: Annotated[Path, typer.Argument(help="Directory within owner home or registered project root")],
    max_entries: Annotated[int, typer.Option("--max-entries", min=1, max=10000)] = 1024,
    max_depth: Annotated[int, typer.Option("--max-depth", min=0, max=12)] = 6,
    timeout_seconds: Annotated[float, typer.Option("--timeout-seconds", min=0.001, max=5.0)] = 2.0,
    limit: Annotated[int, typer.Option("--limit", min=1, max=100)] = 10,
    max_bytes: Annotated[int, typer.Option("--max-bytes", min=512, max=65536)] = 4096,
) -> None:
    """Metadata-only disk attribution with explicit scan coverage."""
    _observe(query_disk_space, max_bytes, path=path, max_entries=max_entries,
             max_depth=max_depth, timeout_seconds=timeout_seconds, limit=limit)


@app.command()
def benchmark(
    kind: Annotated[str, typer.Argument(help="cpu, disk, gpu, or network")],
    duration_seconds: Annotated[float, typer.Option("--duration-seconds", min=0.001, max=3.0)] = 1.0,
    max_bytes: Annotated[int, typer.Option("--max-bytes", min=512, max=65536)] = 4096,
) -> None:
    """Opt-in bounded CPU or cached file-read probe."""
    _observe(run_benchmark, max_bytes, kind=kind, duration_seconds=duration_seconds)


@app.command()
def export(
    since: Annotated[str, typer.Option("--since", help="UTC start of capture interval")],
    until: Annotated[str, typer.Option("--until", help="UTC end of capture interval")],
    limit: Annotated[int, typer.Option("--limit", min=1, max=20)] = 10,
    cursor: Annotated[str | None, typer.Option("--cursor")] = None,
    max_bytes: Annotated[int, typer.Option("--max-bytes", min=512, max=65536)] = 4096,
) -> None:
    """Redacted replay page from committed host samples and capture events."""
    if cursor and (_RELATIVE.fullmatch(since) or _RELATIVE.fullmatch(until)):
        _failure(MonitorQueryError("pagination requires absolute --since and --until from coverage"), max_bytes)
    try:
        result = export_capture(MonitorReader(_state_dir()), _required_time(since), _required_time(until),
                                limit=limit, cursor=cursor, max_bytes=max_bytes)
        _emit(result, max_bytes)
    except (MonitorQueryError, ObserveQueryError) as exc:
        _failure(MonitorQueryError(str(exc)), max_bytes)
