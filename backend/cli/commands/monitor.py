"""Agent-facing queries for the independent system host collector."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any

import typer

from monitor_control import (
    MonitorControlError,
    control_request,
    enrich_status,
    monitor_state_dir,
    observe_request,
)
from monitor_extended import export_capture, run_benchmark
from monitor_observe import (
    ObserveQueryError,
    query_apps,
    query_drivers,
    query_log_services,
    query_sensors,
    query_startup,
    query_system_info,
    query_users,
)
from monitor_reader import MonitorQueryError, MonitorReader

from ..lib.usage import usage

app = typer.Typer(help="System and project troubleshooting: bounded JSON with coverage, freshness, and cursors. Start with status.", no_args_is_help=True)
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


def _privileged(source: str, max_bytes: int, *, limit: int, **params: Any) -> None:
    try:
        _emit(observe_request(source, params, limit=limit, max_bytes=max_bytes), max_bytes)
    except MonitorControlError as exc:
        _failure(MonitorQueryError(str(exc)), max_bytes)


@app.command()
@usage(
    surface="st.monitor.status",
    cmd="st monitor status",
    when="inspect current host and managed-service health without PostgreSQL or backend availability",
    precautions=(
        "start here for system or project troubleshooting; inspect coverage, observation age, errors, and truncated before drawing conclusions",
        "history works without the backend or PostgreSQL; live logs, connections, disk scans, and capture need the host collector",
        "use st monitor --help for queries; st logs tail retains alias/follow views and st runtime metrics reads older application runtime history",
    ),
    examples=("st monitor status", "st monitor status --max-bytes 8192"),
    task_types=("devops", "debugging"),
    on_demand="host and project troubleshooting",
    tier="reference",
)
def status(max_bytes: Annotated[int, typer.Option("--max-bytes", min=512, max=65536)] = 4096) -> None:
    """Latest committed host and managed-service observation."""
    _query("status", max_bytes)


@app.command()
@usage(
    surface='st.monitor.series',
    cmd='st monitor series <metric> --since 15m',
    when='compare host or service metrics over a bounded historical window',
    precautions=(
        'choose a supported metric and entity from command help or query errors; unsupported fields are unavailable, not zero',
        'follow next_cursor with the same absolute since/until window; increasing response bytes does not remove source limits',
    ),
    examples=(
        'st monitor series cpu_busy_pct --since 15m --limit 20 --max-bytes 8192',
    ),
    task_types=("devops", "debugging"),
    on_demand="host and project troubleshooting",
    tier="reference",
)
def series(
    metric: Annotated[str, typer.Argument(help="Whitelisted host or service metric")],
    entity: Annotated[str, typer.Option("--entity", help="host or managed service id")] = "host",
    boot_id: Annotated[str | None, typer.Option("--boot-id", help="Required for gpu:<index> device history")] = None,
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
    _query("series", max_bytes, metric=metric, entity=entity, boot_id=boot_id, since=_time(since), until=_time(until),
           step=step, limit=limit, cursor=cursor)


@app.command()
@usage(
    surface="st.monitor.gpu",
    cmd="st monitor gpu",
    when="inspect the latest retained GPU poll, provider outcome, and boot-scoped device readings",
    precautions=("read-only owner-local history", "poll age and unavailable fields are explicit"),
    examples=("st monitor gpu", "st monitor gpu --limit 1 --max-bytes 4096"),
    task_types=("devops", "debugging"),
    on_demand="host and project troubleshooting",
    tier="reference",
)
def gpu(
    at: Annotated[str | None, typer.Option("--at", help="Latest poll at or before UTC time")] = None,
    limit: Annotated[int, typer.Option("--limit", min=1, max=100)] = 10,
    cursor: Annotated[str | None, typer.Option("--cursor")] = None,
    max_bytes: Annotated[int, typer.Option("--max-bytes", min=512, max=65536)] = 4096,
) -> None:
    """Latest retained NVIDIA poll and bounded per-device readings."""
    _query("gpu", max_bytes, at=_time(at), limit=limit, cursor=cursor)


@app.command()
@usage(
    surface='st.monitor.processes',
    cmd='st monitor processes --sort rss',
    when='find retained process CPU, memory, IO, ownership, and parent-child evidence',
    precautions=(
        'baseline rows are process leaders; use st monitor capture when the problem requires all-process detail',
        'keep the returned observation time with cursor pages; process identity includes boot and start time, not PID alone',
    ),
    examples=(
        'st monitor processes --sort cpu --limit 20 --max-bytes 8192',
        'st monitor processes --name postgres --view tree',
    ),
    task_types=("devops", "debugging"),
    on_demand="host and project troubleshooting",
    tier="reference",
)
def processes(
    at: Annotated[str | None, typer.Option("--at", help="UTC timestamp; defaults to latest")] = None,
    name: Annotated[str | None, typer.Option("--name")] = None,
    user: Annotated[str | None, typer.Option("--user")] = None,
    service: Annotated[str | None, typer.Option("--service")] = None,
    sort: Annotated[str, typer.Option("--sort", help="cpu, rss, io")] = "rss",
    view: Annotated[str, typer.Option("--view", help="list or tree; tree traverses one captured observation")] = "list",
    limit: Annotated[int, typer.Option("--limit", min=1, max=100)] = 10,
    cursor: Annotated[str | None, typer.Option("--cursor")] = None,
    max_bytes: Annotated[int, typer.Option("--max-bytes", min=512, max=65536)] = 4096,
) -> None:
    """Process leaders or bounded detail at a specific sample."""
    _query("processes", max_bytes, at=_time(at), name=name, user=user, service=service,
           sort=sort, view=view, limit=limit, cursor=cursor)


@app.command()
@usage(
    surface='st.monitor.events',
    cmd='st monitor events --since 15m',
    when='correlate source failures, service transitions, and capture triggers with a problem',
    precautions=(
        'events describe recorded observations, not a complete audit log',
        'pagination requires the same absolute since/until window',
    ),
    examples=(
        'st monitor events --since 15m --limit 20 --max-bytes 8192',
    ),
    task_types=("devops", "debugging"),
    on_demand="host and project troubleshooting",
    tier="reference",
)
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
@usage(
    surface='st.monitor.capture',
    cmd='st monitor capture --ttl-seconds 30',
    when='record temporary all-process detail while investigating a live incident',
    precautions=(
        'changes collector sampling detail for a bounded lease; the collector must be running',
        'retain lease_id; use st monitor capture-renew <lease-id> --ttl-seconds 30 or st monitor capture-end <lease-id>',
        'query st monitor processes and export retained evidence; leases expire automatically',
    ),
    examples=(
        'st monitor capture --ttl-seconds 30',
    ),
    task_types=("devops", "debugging"),
    on_demand="host and project troubleshooting",
    tier="reference",
)
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
@usage(
    surface='st.monitor.logs',
    cmd='st monitor logs [service] --scope user --since 15m',
    when='read bounded journal evidence for project services or the whole host',
    precautions=(
        'discover exact unit IDs with st monitor log-services --scope user or --scope system; omit service for the selected journal',
        'collector is required; credential redaction remains enabled and does not imply arbitrary logs are safe to publish',
        'follow cursors with the same absolute since/until window; container scope currently reports unsupported',
    ),
    examples=(
        'st monitor logs summitflow-backend.service --scope user --since 15m',
        'st monitor logs --scope system --priority 3 --since 15m --max-bytes 8192',
    ),
    task_types=("devops", "debugging"),
    on_demand="host and project troubleshooting",
    tier="reference",
)
def logs(
    service: Annotated[str | None, typer.Argument(help="Service unit; omit for the full journal")] = None,
    scope: Annotated[str, typer.Option("--scope", help="user, system, or container logs")] = "user",
    since: Annotated[str | None, typer.Option("--since", help="UTC timestamp or 15m/6h/1d")] = None,
    until: Annotated[str | None, typer.Option("--until", help="UTC timestamp")] = None,
    cursor: Annotated[str | None, typer.Option("--cursor", help="Opaque journal cursor")] = None,
    priority: Annotated[int | None, typer.Option("--priority", min=0, max=7)] = None,
    limit: Annotated[int, typer.Option("--limit", min=1, max=100)] = 10,
    max_bytes: Annotated[int, typer.Option("--max-bytes", min=512, max=65536)] = 4096,
) -> None:
    """Bounded journal entries from the selected host scope."""
    if cursor and (not since or _RELATIVE.fullmatch(since) or not until):
        _failure(MonitorQueryError("pagination requires absolute --since and --until from requested"), max_bytes)
    _privileged("logs", max_bytes, service=service, scope=scope, since=_time(since), until=_time(until),
                cursor=cursor, priority=priority, limit=limit)


@app.command("log-services")
@usage(
    surface='st.monitor.log-services',
    cmd='st monitor log-services --scope user',
    when='discover selectable project and system journal service units before requesting logs',
    precautions=(
        'use user or system scope and reuse the returned exact unit name in st monitor logs',
        'follow next_cursor; discovery and journal access can have different availability',
    ),
    examples=(
        'st monitor log-services --scope user --max-bytes 8192',
        'st monitor log-services --scope system --max-bytes 8192',
    ),
    task_types=("devops", "debugging"),
    on_demand="host and project troubleshooting",
    tier="reference",
)
def log_services(scope: Annotated[str, typer.Option("--scope")] = "user",
                 cursor: Annotated[str | None, typer.Option("--cursor")] = None,
                 limit: Annotated[int, typer.Option("--limit", min=1, max=100)] = 100,
                 max_bytes: Annotated[int, typer.Option("--max-bytes", min=512, max=65536)] = 4096) -> None:
    """List service units available in the selected journal scope."""
    _observe(query_log_services, max_bytes, scope=scope, cursor=cursor, limit=limit)


@app.command()
@usage(
    surface='st.monitor.mounts',
    cmd='st monitor mounts',
    when='locate filesystem capacity and usage before investigating disk consumption',
    precautions=(
        'reads committed collector history; use --at to pin an observation and check coverage',
        'use st monitor disk-space <mount-path> for bounded directory attribution',
    ),
    examples=(
        'st monitor mounts --max-bytes 8192',
        'st monitor mounts --at 2026-09-27T12:00:00Z --max-bytes 8192',
    ),
    task_types=("devops", "debugging"),
    on_demand="host and project troubleshooting",
    tier="reference",
)
def mounts(at: Annotated[str | None, typer.Option("--at", help="Latest observation at or before UTC time")] = None,
           cursor: Annotated[str | None, typer.Option("--cursor")] = None,
           limit: Annotated[int, typer.Option("--limit", min=1, max=100)] = 100,
           max_bytes: Annotated[int, typer.Option("--max-bytes", min=512, max=65536)] = 65536) -> None:
    """Mounted filesystems from a committed collector observation."""
    _query("mounts", max_bytes, at=_time(at), cursor=cursor, limit=limit)


@app.command()
def sensors(
    limit: Annotated[int, typer.Option("--limit", min=1, max=100)] = 10,
    max_bytes: Annotated[int, typer.Option("--max-bytes", min=512, max=65536)] = 4096,
) -> None:
    """Available temperatures, fans, CPU frequencies and power readings."""
    _observe(query_sensors, max_bytes, limit=limit)


@app.command()
@usage(
    surface='st.monitor.connections',
    cmd='st monitor connections',
    when='inspect local and remote socket endpoints and owning processes for connectivity troubleshooting',
    precautions=(
        'collector is required; addresses and process attribution are included by default',
        'follow next_cursor and inspect namespace, table, ownership, and scan coverage; partial results are not absence of activity',
    ),
    examples=(
        'st monitor connections --limit 20 --max-bytes 8192',
    ),
    task_types=("devops", "debugging"),
    on_demand="host and project troubleshooting",
    tier="reference",
)
def connections(
    limit: Annotated[int, typer.Option("--limit", min=1, max=100)] = 10,
    show_addresses: Annotated[bool, typer.Option("--show-addresses", help="Compatibility flag; endpoints are always included")] = True,
    include_process: Annotated[bool, typer.Option("--include-process", help="Compatibility flag; owner lookup is always included")] = True,
    cursor: Annotated[str | None, typer.Option("--cursor")] = None,
    max_bytes: Annotated[int, typer.Option("--max-bytes", min=512, max=65536)] = 4096,
) -> None:
    """On-demand socket states with endpoints and owning processes."""
    _privileged("connections", max_bytes, limit=limit, include_addresses=True,
                include_process=True, cursor=cursor)


@app.command("system-info")
@usage(
    surface='st.monitor.system-info',
    cmd='st monitor system-info',
    when='establish operating-system and hardware context before choosing diagnostics',
    precautions=(
        'read-only inventory; related commands are sensors, users, startup, apps, and drivers under st monitor',
        'startup reports enabled user services; users is an account inventory, not session telemetry',
    ),
    examples=(
        'st monitor system-info',
        'st monitor apps --provider dpkg --name python --max-bytes 8192',
    ),
    task_types=("devops", "debugging"),
    on_demand="host and project troubleshooting",
    tier="reference",
)
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
         provider: Annotated[str, typer.Option("--provider", help="dpkg, snap, or flatpak")] = "dpkg",
         name: Annotated[str | None, typer.Option("--name", help="Case-insensitive package name substring")] = None,
         cursor: Annotated[str | None, typer.Option("--cursor", help="Cursor from previous page")] = None,
         max_bytes: Annotated[int, typer.Option("--max-bytes", min=512, max=65536)] = 4096) -> None:
    """Installed packages from one on-demand provider, bounded and read-only."""
    _observe(query_apps, max_bytes, provider=provider, name=name, cursor=cursor, limit=limit)


@app.command()
def drivers(limit: Annotated[int, typer.Option("--limit", min=1, max=100)] = 10,
            max_bytes: Annotated[int, typer.Option("--max-bytes", min=512, max=65536)] = 4096) -> None:
    """Loaded kernel modules, with no driver control actions."""
    _observe(query_drivers, max_bytes, limit=limit)


@app.command("disk-space")
@usage(
    surface='st.monitor.disk-space',
    cmd='st monitor disk-space <directory>',
    when='attribute disk use within a selected mounted filesystem without reading file contents',
    precautions=(
        'collector is required; discover mounts first and choose the affected directory',
        'entry, depth, time, and filesystem boundaries remain bounded; reported partial totals are observed lower bounds',
        'no symlink traversal; use coverage and errors to distinguish denied, skipped, and truncated paths',
    ),
    examples=(
        'st monitor disk-space /var --max-entries 10000 --max-depth 6 --timeout-seconds 5 --max-bytes 8192',
    ),
    task_types=("devops", "debugging"),
    on_demand="host and project troubleshooting",
    tier="reference",
)
def disk_space(
    path: Annotated[Path, typer.Argument(help="Directory on a mounted filesystem")],
    max_entries: Annotated[int, typer.Option("--max-entries", min=1, max=10000)] = 1024,
    max_depth: Annotated[int, typer.Option("--max-depth", min=0, max=12)] = 6,
    timeout_seconds: Annotated[float, typer.Option("--timeout-seconds", min=0.001, max=5.0)] = 2.0,
    limit: Annotated[int, typer.Option("--limit", min=1, max=100)] = 10,
    max_bytes: Annotated[int, typer.Option("--max-bytes", min=512, max=65536)] = 4096,
) -> None:
    """Metadata-only disk attribution with explicit scan coverage."""
    _privileged("disk_space", max_bytes, path=str(path), max_entries=max_entries,
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
@usage(
    surface='st.monitor.export',
    cmd='st monitor export --since <UTC> --until <UTC>',
    when='replay retained host samples and capture events for an incident window',
    precautions=(
        'reads committed history and works with the collector stopped; does not create a new capture',
        'use an explicit UTC window and follow next_cursor with that same window; export is bounded',
    ),
    examples=(
        'st monitor export --since 2026-09-27T12:00:00Z --until 2026-09-27T12:05:00Z --max-bytes 8192',
    ),
    task_types=("devops", "debugging"),
    on_demand="host and project troubleshooting",
    tier="reference",
)
def export(
    since: Annotated[str, typer.Option("--since", help="UTC start of capture interval")],
    until: Annotated[str, typer.Option("--until", help="UTC end of capture interval")],
    limit: Annotated[int, typer.Option("--limit", min=1, max=20)] = 10,
    cursor: Annotated[str | None, typer.Option("--cursor")] = None,
    max_bytes: Annotated[int, typer.Option("--max-bytes", min=512, max=65536)] = 4096,
) -> None:
    """Replay page from committed host samples and capture events."""
    if cursor and (_RELATIVE.fullmatch(since) or _RELATIVE.fullmatch(until)):
        _failure(MonitorQueryError("pagination requires absolute --since and --until from coverage"), max_bytes)
    try:
        result = export_capture(MonitorReader(_state_dir()), _required_time(since), _required_time(until),
                                limit=limit, cursor=cursor, max_bytes=max_bytes)
        _emit(result, max_bytes)
    except (MonitorQueryError, ObserveQueryError) as exc:
        _failure(MonitorQueryError(str(exc)), max_bytes)
