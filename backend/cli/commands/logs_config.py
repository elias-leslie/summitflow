"""Configuration and data models for log viewing commands."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


def _identity_user_services() -> dict[str, str]:
    """Log names for each project's declared units (project.identity.json services).

    ``<project>`` is the backend (or the frontend when there is none),
    ``<project>-web`` the frontend, ``<project>-worker`` the first default
    worker, and every worker also answers to its unit name without suffix.
    """
    from app.project_identity import list_project_identities

    services: dict[str, str] = {}
    for identity in list_project_identities():
        project = identity.get("project")
        project_id = project.get("id") if isinstance(project, dict) else None
        declared = identity.get("services")
        if not isinstance(project_id, str) or not project_id or not isinstance(declared, dict):
            continue
        backend, frontend = declared.get("backend") or "", declared.get("frontend") or ""
        default_workers = [unit for unit in declared.get("default_workers") or [] if isinstance(unit, str) and unit]
        workers = [*default_workers, *(u for u in declared.get("optional_workers") or [] if isinstance(u, str) and u)]
        names = {project_id: backend or frontend}
        if frontend:
            names[f"{project_id}-web"] = frontend
        if default_workers:
            names[f"{project_id}-worker"] = default_workers[0]
        for unit in workers:
            names[unit.rsplit(".", 1)[0] if unit.endswith((".service", ".timer", ".socket")) else unit] = unit
        for name, unit in names.items():
            if isinstance(unit, str) and unit:
                services.setdefault(name, unit)
    return services


# User services (run with --user flag)
USER_SERVICES = _identity_user_services()

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
