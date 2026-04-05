"""Configuration and data models for log viewing commands."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

# Service name to systemd unit mapping
# User services (run with --user flag)
USER_SERVICES = {
    "portfolio-ai": "portfolio-backend.service",
    "portfolio-companion": "portfolio-dev-companion.service",
    "portfolio-web": "portfolio-frontend.service",
    "portfolio-worker": "portfolio-hatchet-worker.service",
    "summitflow": "summitflow-backend.service",
    "sf-frontend": "summitflow-frontend.service",
    "sf-worker": "summitflow-hatchet-worker.service",
    "agent-hub": "agent-hub-backend.service",
    "ah-frontend": "agent-hub-frontend.service",
    "ah-worker": "agent-hub-hatchet-agent-worker.service",
    "ah-agent-worker": "agent-hub-hatchet-agent-worker.service",
    "ah-ops-worker": "agent-hub-hatchet-ops-worker.service",
    "aterm": "aterm-backend.service",
    "vantage": "vantage-backend.service",
    "vantage-web": "vantage-frontend.service",
    "vantage-worker": "vantage-hatchet-worker.service",
    "monkey-fight": "monkey-fight.service",
    "test1": "test1-backend.service",
    "test1-web": "test1-frontend.service",
    "test2": "test2-backend.service",
    "test2-web": "test2-frontend.service",
    "test3": "test3-backend.service",
    "test3-web": "test3-frontend.service",
}

# System services (run without --user flag)
SYSTEM_SERVICES = {
    "redis": "redis-server.service",
    "postgres": "postgresql.service",
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

# Default time window for log queries
DEFAULT_SINCE = "30 minutes ago"

# Number of log entries to scan for the levels command
LEVELS_SCAN_LINES = 1000

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

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "service": self.service,
            "level": self.level,
            "message": self.message,
        }


_SHORTHAND_UNITS = {
    "m": "minutes",
    "min": "minutes",
    "h": "hours",
    "hr": "hours",
    "d": "days",
}


def _expand_shorthand(since: str) -> str | None:
    """Expand shorthand like '2m', '1h', '3d' into journalctl-compatible form."""
    import re

    match = re.fullmatch(r"(\d+)\s*([a-z]+)", since)
    if not match:
        return None
    value, unit = match.group(1), match.group(2)
    expanded_unit = _SHORTHAND_UNITS.get(unit)
    if expanded_unit is None:
        return None
    return f"{value} {expanded_unit} ago"


def validate_since(since: str) -> str:
    """Validate since parameter to prevent command injection."""
    since_lower = since.lower().strip()

    # Try expanding shorthand first (e.g. "2m" -> "2 minutes ago")
    expanded = _expand_shorthand(since_lower)
    if expanded:
        return expanded

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


def get_service_list(service: str | None) -> tuple[list[str], list[str]]:
    """Parse service filter into user and system service lists."""
    if not service or service == "all":
        return list(USER_SERVICES.keys()), list(SYSTEM_SERVICES.keys())

    # Split by comma
    requested = [s.strip().lower() for s in service.split(",")]
    user_svcs = [s for s in requested if s in USER_SERVICES]
    system_svcs = [s for s in requested if s in SYSTEM_SERVICES]

    return user_svcs, system_svcs
