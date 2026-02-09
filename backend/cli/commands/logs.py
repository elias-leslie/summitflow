"""Log viewing commands using systemd journal.

Provides unified log tailing across SummitFlow and Agent Hub services.
Based on portfolio-ai's journalctl integration pattern.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated

import typer

from ..output import output_error, output_json
from ..output_context import OutputContext

app = typer.Typer(help="View and tail service logs")

# Service name to systemd unit mapping
# User services (run with --user flag)
USER_SERVICES = {
    "summitflow": "summitflow-backend.service",
    "sf-frontend": "summitflow-frontend.service",
    "sf-worker": "summitflow-hatchet-worker.service",
    "agent-hub": "agent-hub-backend.service",
    "ah-frontend": "agent-hub-frontend.service",
    "ah-worker": "agent-hub-hatchet-worker.service",
    "terminal": "summitflow-terminal.service",
}

# System services (run without --user flag)
SYSTEM_SERVICES = {
    "redis": "redis-server.service",
    "postgres": "postgresql.service",
    "neo4j": "neo4j.service",
}

# All services
ALL_SERVICES = {**USER_SERVICES, **SYSTEM_SERVICES}

# Syslog priority to level mapping
SYSLOG_PRIORITY_TO_LEVEL = {
    0: "CRITICAL",  # emerg
    1: "CRITICAL",  # alert
    2: "CRITICAL",  # crit
    3: "ERROR",  # err
    4: "WARN",  # warning
    5: "INFO",  # notice
    6: "INFO",  # info
    7: "DEBUG",  # debug
}

# Valid time range values
VALID_SINCE = [
    "5 minutes ago",
    "15 minutes ago",
    "30 minutes ago",
    "1 hour ago",
    "2 hours ago",
    "today",
    "yesterday",
]


@dataclass
class LogEntry:
    """A parsed log entry."""

    timestamp: datetime
    service: str
    level: str
    message: str

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "service": self.service,
            "level": self.level,
            "message": self.message,
        }


def _validate_since(since: str) -> str:
    """Validate since parameter to prevent command injection."""
    since_lower = since.lower().strip()

    # Check exact matches
    for valid in VALID_SINCE:
        if since_lower == valid:
            return since_lower

    # Check patterns like "N minutes ago", "N hours ago"
    parts = since_lower.split()
    if len(parts) == 3 and parts[2] == "ago":
        try:
            int(parts[0])
            if parts[1] in ("minute", "minutes", "hour", "hours", "day", "days"):
                return since_lower
        except ValueError:
            pass

    # Default to 30 minutes
    return "30 minutes ago"


def _extract_timestamp(entry: dict) -> datetime:
    """Extract timestamp from journald entry."""
    timestamp_us = int(entry.get("__REALTIME_TIMESTAMP", 0))
    return datetime.fromtimestamp(timestamp_us / 1000000, tz=UTC)


def _map_service(entry: dict) -> str:
    """Map systemd unit to service name."""
    # User services use _SYSTEMD_USER_UNIT, system services use _SYSTEMD_UNIT
    unit = str(
        entry.get("_SYSTEMD_USER_UNIT", "")
        or entry.get("_SYSTEMD_UNIT", "")
        or entry.get("UNIT", "")
    )
    if not unit:
        return "unknown"

    # Check exact matches first
    for svc, unit_name in ALL_SERVICES.items():
        if unit == unit_name:
            return svc

    # Check partial matches (unit_name is substring of unit)
    for svc, unit_name in ALL_SERVICES.items():
        if unit_name in unit:
            return svc

    # Try to extract a reasonable name from the unit
    # e.g., "summitflow-backend.service" -> "summitflow"
    if unit.endswith(".service"):
        unit = unit[:-8]  # Remove ".service"
    parts = unit.split("-")
    if parts:
        return parts[0]

    return "unknown"


def _extract_message(entry: dict) -> str | None:
    """Extract and decode message from journald entry."""
    message_raw = entry.get("MESSAGE", "")
    if isinstance(message_raw, list):
        try:
            return "".join(chr(b) if isinstance(b, int) else str(b) for b in message_raw)
        except (ValueError, TypeError):
            return None
    return str(message_raw)


def _determine_level(entry: dict) -> str:
    """Determine log level from journald PRIORITY field."""
    priority = int(entry.get("PRIORITY", 6))  # Default to info
    return SYSLOG_PRIORITY_TO_LEVEL.get(priority, "INFO")


def _is_control_message(message: str) -> bool:
    """Check if message is a systemd control message."""
    return any(
        message.startswith(prefix) for prefix in ("Starting ", "Started ", "Stopping ", "Stopped ")
    )


def _fetch_logs(
    services: list[str],
    is_user_mode: bool,
    lines: int,
    since: str,
) -> list[LogEntry]:
    """Fetch logs from journald."""
    if not services:
        return []

    cmd = [
        "journalctl",
        "--no-pager",
        "-o",
        "json",
        "--since",
        since,
        "-n",
        str(lines),
    ]

    if is_user_mode:
        cmd.insert(1, "--user")

    for svc in services:
        unit = ALL_SERVICES.get(svc)
        if unit:
            cmd.extend(["-u", unit])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if result.returncode != 0:
            return []

        logs: list[LogEntry] = []
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            try:
                entry = json.loads(line)
                message = _extract_message(entry)
                if not message or not message.strip():
                    continue
                if _is_control_message(message):
                    continue

                logs.append(
                    LogEntry(
                        timestamp=_extract_timestamp(entry),
                        service=_map_service(entry),
                        level=_determine_level(entry),
                        message=message.strip(),
                    )
                )
            except (json.JSONDecodeError, KeyError, ValueError):
                continue

        return logs

    except subprocess.TimeoutExpired:
        return []
    except Exception:
        return []


def _format_logs_compact(logs: list[LogEntry], show_header: bool = True) -> None:
    """Format logs in TOON style.

    Format:
    LOGS[N]:services=X
    {timestamp} {service:12} {level:5} {message}
    """
    if show_header:
        services = len(set(log.service for log in logs))
        print(f"LOGS[{len(logs)}]:services={services}")

    for log in logs:
        ts = log.timestamp.strftime("%H:%M:%S")
        svc = log.service[:12].ljust(12)
        lvl = log.level[:5].ljust(5)
        msg = log.message
        if len(msg) > 100:
            msg = msg[:97] + "..."
        print(f"  {ts} {svc} {lvl} {msg}")


def _get_service_list(service: str | None) -> tuple[list[str], list[str]]:
    """Parse service filter into user and system service lists."""
    if not service or service == "all":
        return list(USER_SERVICES.keys()), list(SYSTEM_SERVICES.keys())

    # Split by comma
    requested = [s.strip().lower() for s in service.split(",")]
    user_svcs = [s for s in requested if s in USER_SERVICES]
    system_svcs = [s for s in requested if s in SYSTEM_SERVICES]

    return user_svcs, system_svcs


@app.callback(invoke_without_command=True)
def logs_default(ctx: typer.Context) -> None:
    """View unified logs from SummitFlow and Agent Hub services.

    Without a subcommand, shows the tail of recent logs.
    """
    if ctx.obj is None:
        ctx.obj = OutputContext()
    if ctx.invoked_subcommand is None:
        tail(ctx)


@app.command()
def tail(
    ctx: typer.Context,
    service: Annotated[
        str | None,
        typer.Option(
            "--service",
            "-s",
            help="Filter by service (summitflow,agent-hub,redis,postgres,neo4j,all)",
        ),
    ] = None,
    level: Annotated[
        str | None,
        typer.Option(
            "--level",
            "-l",
            help="Filter by level (ERROR,WARN,INFO,DEBUG)",
        ),
    ] = None,
    lines: Annotated[
        int,
        typer.Option(
            "--lines",
            "-n",
            help="Number of lines to show",
        ),
    ] = 100,
    since: Annotated[
        str,
        typer.Option(
            "--since",
            help="Time range (e.g., '30 minutes ago', '1 hour ago', 'today')",
        ),
    ] = "30 minutes ago",
    follow: Annotated[
        bool,
        typer.Option(
            "--follow",
            "-f",
            help="Follow log output (like tail -f)",
        ),
    ] = False,
) -> None:
    """Tail service logs with filtering.

    Examples:
        st logs tail
        st logs tail --service summitflow
        st logs tail -s agent-hub --level ERROR
        st logs tail --since "1 hour ago" --lines 200
        st logs tail -f  # Follow mode
    """
    validated_since = _validate_since(since)
    user_svcs, system_svcs = _get_service_list(service)

    if follow:
        # Use journalctl --follow directly
        _follow_logs(user_svcs, system_svcs, level)
        return

    # Fetch from both user and system services
    all_logs: list[LogEntry] = []

    if user_svcs:
        all_logs.extend(
            _fetch_logs(user_svcs, is_user_mode=True, lines=lines, since=validated_since)
        )
    if system_svcs:
        all_logs.extend(
            _fetch_logs(system_svcs, is_user_mode=False, lines=lines, since=validated_since)
        )

    # Sort by timestamp
    all_logs.sort(key=lambda x: x.timestamp)

    # Filter by level if specified
    if level:
        level_upper = level.upper()
        all_logs = [log for log in all_logs if log.level == level_upper]

    # Limit to requested number
    all_logs = all_logs[-lines:]

    if not all_logs:
        output_error("No logs found")
        return

    if ctx.obj.is_compact:
        _format_logs_compact(all_logs)
    else:
        output_json([log.to_dict() for log in all_logs])


def _follow_logs(
    user_svcs: list[str],
    system_svcs: list[str],
    level: str | None,
) -> None:
    """Follow logs in real-time using journalctl --follow."""
    # Build command for user services (our main services)
    if not user_svcs:
        user_svcs = list(USER_SERVICES.keys())

    cmd = ["journalctl", "--user", "--follow", "--no-pager", "-o", "cat"]

    for svc in user_svcs:
        unit = USER_SERVICES.get(svc)
        if unit:
            cmd.extend(["-u", unit])

    # Add priority filter if specified
    if level:
        level_upper = level.upper()
        priority_map = {"CRITICAL": "2", "ERROR": "3", "WARN": "4", "INFO": "6", "DEBUG": "7"}
        if level_upper in priority_map:
            cmd.extend(["-p", priority_map[level_upper]])

    try:
        print(f"Following logs for: {', '.join(user_svcs)} (Ctrl+C to stop)")
        subprocess.run(cmd, check=False)
    except KeyboardInterrupt:
        print("\nStopped following logs")


@app.command()
def services(ctx: typer.Context) -> None:
    """List available service names for filtering.

    Examples:
        st logs services
    """
    if ctx.obj.is_compact:
        print("SERVICES:user")
        for name, unit in USER_SERVICES.items():
            print(f"  {name:15} {unit}")
        print("SERVICES:system")
        for name, unit in SYSTEM_SERVICES.items():
            print(f"  {name:15} {unit}")
    else:
        output_json(
            {
                "user_services": USER_SERVICES,
                "system_services": SYSTEM_SERVICES,
            }
        )


@app.command()
def levels(ctx: typer.Context) -> None:
    """Show log level counts from recent logs.

    Examples:
        st logs levels
    """
    user_svcs, system_svcs = _get_service_list("all")
    since = "30 minutes ago"
    lines = 1000

    all_logs: list[LogEntry] = []
    if user_svcs:
        all_logs.extend(_fetch_logs(user_svcs, is_user_mode=True, lines=lines, since=since))
    if system_svcs:
        all_logs.extend(_fetch_logs(system_svcs, is_user_mode=False, lines=lines, since=since))

    # Count by level
    counts: dict[str, int] = {}
    for log in all_logs:
        counts[log.level] = counts.get(log.level, 0) + 1

    if ctx.obj.is_compact:
        total = sum(counts.values())
        print(f"LEVELS:total={total}:since=30m")
        for lvl in ["CRITICAL", "ERROR", "WARN", "INFO", "DEBUG"]:
            count = counts.get(lvl, 0)
            if count > 0:
                print(f"  {lvl:8} {count}")
    else:
        output_json({"counts": counts, "total": len(all_logs), "since": since})
