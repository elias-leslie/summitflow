"""Log fetching and processing from systemd journal."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from typing import Any

from .logs_config import (
    ALL_SERVICES,
    SYSLOG_PRIORITY_TO_LEVEL,
    USER_SERVICES,
    LogEntry,
)

JOURNALCTL = "journalctl"
SUBPROCESS_TIMEOUT = 15
MSG_MAX_LEN = 100
MSG_TRUNCATE_LEN = 97
SVC_DISPLAY_WIDTH = 12
LVL_DISPLAY_WIDTH = 5
SERVICE_SUFFIX = ".service"
CONTROL_PREFIXES = ("Starting ", "Started ", "Stopping ", "Stopped ")
LEVEL_TO_PRIORITY = {"CRITICAL": "2", "ERROR": "3", "WARN": "4", "INFO": "6", "DEBUG": "7"}


def extract_timestamp(entry: dict[str, Any]) -> datetime:
    """Extract timestamp from journald entry."""
    return datetime.fromtimestamp(int(entry.get("__REALTIME_TIMESTAMP", 0)) / 1_000_000, tz=UTC)


def map_service(entry: dict[str, Any]) -> str:
    """Map systemd unit to service name."""
    unit = str(entry.get("_SYSTEMD_USER_UNIT", "") or entry.get("_SYSTEMD_UNIT", "") or entry.get("UNIT", ""))
    if not unit:
        return "unknown"
    for svc, unit_name in ALL_SERVICES.items():
        if unit == unit_name:
            return svc
    for svc, unit_name in ALL_SERVICES.items():
        if unit_name in unit:
            return svc
    base = unit[: -len(SERVICE_SUFFIX)] if unit.endswith(SERVICE_SUFFIX) else unit
    parts = base.split("-")
    return parts[0] if parts else "unknown"


def extract_message(entry: dict[str, Any]) -> str | None:
    """Extract and decode message from journald entry."""
    raw = entry.get("MESSAGE", "")
    if not isinstance(raw, list):
        return str(raw)
    try:
        return "".join(chr(b) if isinstance(b, int) else str(b) for b in raw)
    except (ValueError, TypeError):
        return None


def determine_level(entry: dict[str, Any]) -> str:
    """Determine log level from journald PRIORITY field."""
    return SYSLOG_PRIORITY_TO_LEVEL.get(int(entry.get("PRIORITY", 6)), "INFO")


def is_control_message(message: str) -> bool:
    """Check if message is a systemd control message."""
    return any(message.startswith(prefix) for prefix in CONTROL_PREFIXES)


def _parse_log_line(line: str) -> LogEntry | None:
    """Parse a single JSON journal line into a LogEntry, or None if invalid."""
    if not line:
        return None
    try:
        entry = json.loads(line)
        message = extract_message(entry)
        if not message or not message.strip() or is_control_message(message):
            return None
        return LogEntry(
            timestamp=extract_timestamp(entry),
            service=map_service(entry),
            level=determine_level(entry),
            message=message.strip(),
        )
    except (json.JSONDecodeError, KeyError, ValueError, TypeError):
        return None


def fetch_logs(services: list[str], is_user_mode: bool, lines: int, since: str) -> list[LogEntry]:
    """Fetch logs from journald."""
    if not services:
        return []
    cmd = [JOURNALCTL, "--no-pager", "-o", "json", "--since", since, "-n", str(lines)]
    if is_user_mode:
        cmd.insert(1, "--user")
    for svc in services:
        unit = ALL_SERVICES.get(svc)
        if unit:
            cmd.extend(["-u", unit])
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=SUBPROCESS_TIMEOUT, check=False)
    except Exception:
        return []
    if result.returncode != 0:
        return []
    return [log for log in (_parse_log_line(ln) for ln in result.stdout.strip().split("\n")) if log is not None]


def format_logs_compact(logs: list[LogEntry], show_header: bool = True) -> None:
    """Format logs in TOON style: LOGS[N]:services=X / {ts} {svc} {lvl} {msg}."""
    if show_header:
        print(f"LOGS[{len(logs)}]:services={len(set(log.service for log in logs))}")
    for log in logs:
        ts = log.timestamp.strftime("%H:%M:%S")
        svc = log.service[:SVC_DISPLAY_WIDTH].ljust(SVC_DISPLAY_WIDTH)
        lvl = log.level[:LVL_DISPLAY_WIDTH].ljust(LVL_DISPLAY_WIDTH)
        msg = log.message if len(log.message) <= MSG_MAX_LEN else log.message[:MSG_TRUNCATE_LEN] + "..."
        print(f"  {ts} {svc} {lvl} {msg}")


def follow_logs(user_svcs: list[str], system_svcs: list[str], level: str | None) -> None:
    """Follow logs in real-time using journalctl --follow."""
    if not user_svcs:
        user_svcs = list(USER_SERVICES.keys())
    cmd = [JOURNALCTL, "--user", "--follow", "--no-pager", "-o", "cat"]
    for svc in user_svcs:
        unit = USER_SERVICES.get(svc)
        if unit:
            cmd.extend(["-u", unit])
    if level:
        priority = LEVEL_TO_PRIORITY.get(level.upper())
        if priority:
            cmd.extend(["-p", priority])
    try:
        print(f"Following logs for: {', '.join(user_svcs)} (Ctrl+C to stop)")
        subprocess.run(cmd, check=False)
    except KeyboardInterrupt:
        print("\nStopped following logs")


def collect_all_logs(user_svcs: list[str], system_svcs: list[str], lines: int, since: str) -> list[LogEntry]:
    """Fetch and merge logs from user and system services sorted by timestamp."""
    logs = (fetch_logs(user_svcs, True, lines, since) if user_svcs else []) + (
        fetch_logs(system_svcs, False, lines, since) if system_svcs else []
    )
    logs.sort(key=lambda x: x.timestamp)
    return logs
