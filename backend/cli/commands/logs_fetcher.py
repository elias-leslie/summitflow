"""Log fetching and processing from systemd journal."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime

from .logs_config import ALL_SERVICES, SYSLOG_PRIORITY_TO_LEVEL, USER_SERVICES, LogEntry


def extract_timestamp(entry: dict) -> datetime:
    """Extract timestamp from journald entry."""
    timestamp_us = int(entry.get("__REALTIME_TIMESTAMP", 0))
    return datetime.fromtimestamp(timestamp_us / 1000000, tz=UTC)


def map_service(entry: dict) -> str:
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


def extract_message(entry: dict) -> str | None:
    """Extract and decode message from journald entry."""
    message_raw = entry.get("MESSAGE", "")
    if isinstance(message_raw, list):
        try:
            return "".join(chr(b) if isinstance(b, int) else str(b) for b in message_raw)
        except (ValueError, TypeError):
            return None
    return str(message_raw)


def determine_level(entry: dict) -> str:
    """Determine log level from journald PRIORITY field."""
    priority = int(entry.get("PRIORITY", 6))  # Default to info
    return SYSLOG_PRIORITY_TO_LEVEL.get(priority, "INFO")


def is_control_message(message: str) -> bool:
    """Check if message is a systemd control message."""
    return any(
        message.startswith(prefix) for prefix in ("Starting ", "Started ", "Stopping ", "Stopped ")
    )


def fetch_logs(
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
                message = extract_message(entry)
                if not message or not message.strip():
                    continue
                if is_control_message(message):
                    continue

                logs.append(
                    LogEntry(
                        timestamp=extract_timestamp(entry),
                        service=map_service(entry),
                        level=determine_level(entry),
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


def format_logs_compact(logs: list[LogEntry], show_header: bool = True) -> None:
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


def follow_logs(
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
