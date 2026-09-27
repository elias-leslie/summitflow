"""Standard-library entry point for owner-local ``st monitor`` queries.

The installed launcher runs this file with the system Python, independently of
the backend virtual environment and its application import graph.
"""

from __future__ import annotations

import argparse
import math
import re
from datetime import UTC, datetime, timedelta
from typing import Any

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
from monitor_reader import MonitorQueryError, MonitorReader, encode_budgeted_json

_RELATIVE = re.compile(r"^(\d+)([mhd])$")


def _bounded_int(low: int, high: int):
    def parse(value: str) -> int:
        try:
            number = int(value)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(f"expected integer {low}..{high}") from exc
        if not low <= number <= high:
            raise argparse.ArgumentTypeError(f"expected integer {low}..{high}")
        return number
    return parse


def _bounded_float(low: float, high: float):
    def parse(value: str) -> float:
        try:
            number = float(value)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(f"expected number {low}..{high}") from exc
        if not math.isfinite(number) or not low <= number <= high:
            raise argparse.ArgumentTypeError(f"expected number {low}..{high}")
        return number
    return parse


def _time(value: str | None) -> str | None:
    if value is None:
        return None
    match = _RELATIVE.fullmatch(value)
    if match:
        amount = int(match.group(1))
        unit = {"m": 60, "h": 3600, "d": 86400}[match.group(2)]
        try:
            return (datetime.now(UTC) - timedelta(seconds=amount * unit)).isoformat()
        except OverflowError as exc:
            raise MonitorQueryError("invalid UTC time") from exc
    return value


def _required_time(value: str | None) -> str:
    parsed = _time(value)
    if parsed is None:
        raise MonitorQueryError("UTC time is required")
    return parsed


def _failure(exc: MonitorQueryError, max_bytes: int) -> int:
    message = str(exc)
    code = "collector_stopped" if "store unavailable" in message else "query_error"
    payload = {
        "schema": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "requested": {},
        "coverage": {"availability": code},
        "items": [],
        "next_cursor": None,
        "truncated": False,
        "errors": [{"code": code, "message": message[:200]}],
    }
    print(encode_budgeted_json(payload, max_bytes))
    return 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="st monitor", description="Bounded local host telemetry and troubleshooting history")
    commands = parser.add_subparsers(dest="command", required=True)
    budget = _bounded_int(512, 65536)
    limit = _bounded_int(1, 100)
    ttl = _bounded_int(1, 300)

    status = commands.add_parser("status", help="Latest host and managed-service observation")
    status.add_argument("--max-bytes", type=budget, default=4096)

    series = commands.add_parser("series", help="Bucketed metric timeline")
    series.add_argument("metric")
    series.add_argument("--entity", default="host")
    series.add_argument("--boot-id")
    series.add_argument("--since")
    series.add_argument("--until")
    series.add_argument("--step", type=_bounded_int(5, 3600), default=60)
    series.add_argument("--limit", type=limit, default=10)
    series.add_argument("--cursor")
    series.add_argument("--max-bytes", type=budget, default=4096)

    gpu = commands.add_parser("gpu", help="Latest retained GPU poll and device readings")
    gpu.add_argument("--at")
    gpu.add_argument("--limit", type=limit, default=10)
    gpu.add_argument("--cursor")
    gpu.add_argument("--max-bytes", type=budget, default=4096)

    processes = commands.add_parser("processes", help="Process leaders or detail at a sample")
    processes.add_argument("--at")
    processes.add_argument("--name")
    processes.add_argument("--user")
    processes.add_argument("--service")
    processes.add_argument("--sort", default="rss")
    processes.add_argument("--view", choices=("list", "tree"), default="list")
    processes.add_argument("--limit", type=limit, default=10)
    processes.add_argument("--cursor")
    processes.add_argument("--max-bytes", type=budget, default=4096)

    events = commands.add_parser("events", help="Source, service, and capture events")
    events.add_argument("--since")
    events.add_argument("--until")
    events.add_argument("--kind")
    events.add_argument("--severity")
    events.add_argument("--entity")
    events.add_argument("--limit", type=limit, default=10)
    events.add_argument("--cursor")
    events.add_argument("--max-bytes", type=budget, default=4096)

    capture = commands.add_parser("capture", help="Start a short process-detail lease")
    capture.add_argument("--ttl-seconds", type=ttl, default=30)
    renew = commands.add_parser("capture-renew", help="Renew a process-detail lease")
    renew.add_argument("lease_id")
    renew.add_argument("--ttl-seconds", type=ttl, default=30)
    end = commands.add_parser("capture-end", help="End a process-detail lease")
    end.add_argument("lease_id")

    logs = commands.add_parser("logs", help="Journal entries from user or system services")
    logs.add_argument("service", nargs="?")
    logs.add_argument("--scope", choices=("user", "system", "container"), default="user")
    logs.add_argument("--since")
    logs.add_argument("--until")
    logs.add_argument("--cursor")
    logs.add_argument("--priority", type=_bounded_int(0, 7))
    logs.add_argument("--limit", type=limit, default=10)
    logs.add_argument("--max-bytes", type=budget, default=4096)

    log_services = commands.add_parser("log-services", help="Discover selectable service units")
    log_services.add_argument("--scope", choices=("user", "system", "container"), default="user")
    log_services.add_argument("--cursor")
    log_services.add_argument("--limit", type=limit, default=100)
    log_services.add_argument("--max-bytes", type=budget, default=4096)

    mounts = commands.add_parser("mounts", help="Mounted filesystems from the committed collector sample")
    mounts.add_argument("--at")
    mounts.add_argument("--cursor")
    mounts.add_argument("--limit", type=limit, default=100)
    mounts.add_argument("--max-bytes", type=budget, default=65536)

    for name, help_text in (
        ("sensors", "Temperatures, fans, CPU frequencies and power readings"),
        ("users", "Local account inventory"),
        ("startup", "Enabled user service inventory"),
        ("apps", "Installed packages from one selected provider"),
        ("drivers", "Loaded kernel modules"),
    ):
        inventory = commands.add_parser(name, help=help_text)
        inventory.add_argument("--limit", type=limit, default=10)
        inventory.add_argument("--max-bytes", type=budget, default=4096)
        if name == "apps":
            inventory.add_argument("--provider", choices=("dpkg", "snap", "flatpak"), default="dpkg")
            inventory.add_argument("--name")
            inventory.add_argument("--cursor")

    connections = commands.add_parser("connections", help="On-demand socket states")
    connections.add_argument("--limit", type=limit, default=10)
    connections.add_argument("--show-addresses", action="store_true")
    connections.add_argument("--include-process", action="store_true")
    connections.add_argument("--cursor")
    connections.add_argument("--max-bytes", type=budget, default=4096)

    system_info = commands.add_parser("system-info", help="Static OS and hardware information")
    system_info.add_argument("--max-bytes", type=budget, default=4096)

    disk_space = commands.add_parser("disk-space", help="Metadata-only attribution on a mounted filesystem")
    disk_space.add_argument("path")
    disk_space.add_argument("--max-entries", type=_bounded_int(1, 10000), default=1024)
    disk_space.add_argument("--max-depth", type=_bounded_int(0, 12), default=6)
    disk_space.add_argument("--timeout-seconds", type=_bounded_float(0.001, 5.0), default=2.0)
    disk_space.add_argument("--limit", type=limit, default=10)
    disk_space.add_argument("--max-bytes", type=budget, default=4096)

    benchmark = commands.add_parser("benchmark", help="Opt-in bounded CPU or cached file-read probe")
    benchmark.add_argument("kind", choices=("cpu", "disk", "gpu", "network"))
    benchmark.add_argument("--duration-seconds", type=_bounded_float(0.001, 3.0), default=1.0)
    benchmark.add_argument("--max-bytes", type=budget, default=4096)

    export = commands.add_parser("export", help="Replay committed samples and events")
    export.add_argument("--since", required=True)
    export.add_argument("--until", required=True)
    export.add_argument("--limit", type=_bounded_int(1, 20), default=10)
    export.add_argument("--cursor")
    export.add_argument("--max-bytes", type=budget, default=4096)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    command = args.command
    max_bytes = getattr(args, "max_bytes", 4096)
    try:
        if command in {"series", "events"} and args.cursor and (
            not args.since or _RELATIVE.fullmatch(args.since) or not args.until
        ):
            raise MonitorQueryError("pagination requires absolute --since and --until from coverage")
        if command == "logs" and args.cursor and (
            not args.since or _RELATIVE.fullmatch(args.since) or not args.until
        ):
            raise MonitorQueryError("pagination requires absolute --since and --until from requested")
        if command == "export" and args.cursor and (
            _RELATIVE.fullmatch(args.since) or _RELATIVE.fullmatch(args.until)
        ):
            raise MonitorQueryError("pagination requires absolute --since and --until from coverage")
        if command in {"capture", "capture-renew", "capture-end"}:
            operation = {"capture": "lease_start", "capture-renew": "lease_renew", "capture-end": "lease_end"}[command]
            options: dict[str, Any] = {}
            if command != "capture-end":
                options["ttl_seconds"] = args.ttl_seconds
            if command != "capture":
                options["lease_id"] = args.lease_id
            result = control_request(operation, **options)
            if not result["ok"]:
                raise MonitorControlError(str(result.get("error", "lease operation rejected")))
        elif command == "logs":
            result = observe_request("logs", {"service": args.service, "scope": args.scope,
                                              "since": _time(args.since), "until": _time(args.until),
                                              "cursor": args.cursor, "priority": args.priority},
                                     limit=args.limit, max_bytes=max_bytes)
        elif command == "log-services":
            result = query_log_services(scope=args.scope, cursor=args.cursor, limit=args.limit, max_bytes=max_bytes)
        elif command == "connections":
            result = observe_request("connections", {"include_addresses": True, "include_process": True,
                                                     "cursor": args.cursor}, limit=args.limit, max_bytes=max_bytes)
        elif command == "system-info":
            result = query_system_info(max_bytes=max_bytes)
        elif command == "disk-space":
            result = observe_request("disk_space", {"path": args.path, "max_entries": args.max_entries,
                                                    "max_depth": args.max_depth,
                                                    "timeout_seconds": args.timeout_seconds},
                                     limit=args.limit, max_bytes=max_bytes)
        elif command == "mounts":
            result = MonitorReader(monitor_state_dir()).mounts(at=_time(args.at), cursor=args.cursor, limit=args.limit,
                                                               max_bytes=max_bytes)
        elif command == "benchmark":
            result = run_benchmark(args.kind, duration_seconds=args.duration_seconds,
                                   max_bytes=max_bytes)
        elif command == "export":
            result = export_capture(MonitorReader(monitor_state_dir()), _required_time(args.since),
                                    _required_time(args.until), limit=args.limit, cursor=args.cursor,
                                    max_bytes=max_bytes)
        elif command == "apps":
            result = query_apps(provider=args.provider, name=args.name, cursor=args.cursor, limit=args.limit,
                                max_bytes=max_bytes)
        elif command in {"sensors", "users", "startup", "drivers"}:
            query = {"sensors": query_sensors, "users": query_users, "startup": query_startup,
                     "drivers": query_drivers}[command]
            result = query(limit=args.limit, max_bytes=max_bytes)
        else:
            reader = MonitorReader(monitor_state_dir())
            if command == "status":
                result = enrich_status(reader.status(max_bytes=max_bytes), max_bytes)
            elif command == "series":
                result = reader.series(args.metric, entity=args.entity, boot_id=args.boot_id, since=_time(args.since),
                                       until=_time(args.until), step=args.step, limit=args.limit,
                                       cursor=args.cursor, max_bytes=max_bytes)
            elif command == "gpu":
                result = reader.gpu(at=_time(args.at), limit=args.limit, cursor=args.cursor,
                                    max_bytes=max_bytes)
            elif command == "processes":
                result = reader.processes(at=_time(args.at), name=args.name, user=args.user,
                                          service=args.service, sort=args.sort, view=args.view, limit=args.limit,
                                          cursor=args.cursor, max_bytes=max_bytes)
            else:
                result = reader.events(since=_time(args.since), until=_time(args.until),
                                       kind=args.kind, severity=args.severity, entity=args.entity,
                                       limit=args.limit, cursor=args.cursor, max_bytes=max_bytes)
        print(encode_budgeted_json(result, max_bytes))
        return 0
    except (MonitorQueryError, MonitorControlError, ObserveQueryError) as exc:
        return _failure(MonitorQueryError(str(exc)), max_bytes)


if __name__ == "__main__":
    raise SystemExit(main())
