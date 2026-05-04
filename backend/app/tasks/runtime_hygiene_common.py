"""Shared helpers for runtime hygiene checks."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

WORKFLOW_NAME = "runtime_hygiene"
PROJECTS: tuple[str, ...] = ("summitflow", "agent-hub")
JOURNAL_PATTERNS = {
    "summitflow": "summitflow-*",
    "agent-hub": "agent-hub-*",
}
TARGET_BACKUP_SOURCES = {
    "summitflow": "summitflow",
    "agent-hub": "agent-hub",
}
INFRA_SOURCE_ID = "infrastructure"
ROOT_MOUNT = "/"
HOST_SCOPE = "host"
RUNTIME_CTX_KEY = "runtime_hygiene"
DONE_WHEN = [
    "The runtime_hygiene fingerprint in task context no longer reproduces, or the issue is explicitly accepted with evidence.",
    "Any safe verification for this issue is captured in the task log or description before closeout.",
    "No unrelated remediation is bundled into the fix.",
]

DISK_WARN_PERCENT = 80.0
DISK_CRIT_PERCENT = 90.0
DISK_REMEDIATE_FREE_GB = 15.0
DISK_CRIT_FREE_GB = 10.0
MEMORY_WARN_PERCENT = 85.0
MEMORY_CRIT_PERCENT = 95.0
CPU_WARN_PERCENT = 80.0
CPU_CRIT_PERCENT = 90.0

BACKUP_FRESH_HOURS = 36.0
INFRA_DRILL_STALE_HOURS = 48.0
RESTORE_TEST_STALE_HOURS = 8 * 24.0
JOURNAL_LOOKBACK = "24 hours ago"
JOURNAL_TASK_LIMIT = 5

MIN_BLOAT_TABLE_BYTES = 64 * 1024 * 1024
MIN_BLOAT_DEAD_TUPLES = 1000
BLOAT_WARN_PCT = 10.0
BLOAT_CRIT_PCT = 20.0
BLOAT_CRIT_DEAD_BYTES = 128 * 1024 * 1024
MAX_VACUUM_TABLES_PER_DB = 3

ACTION_COOLDOWN_HOURS = {
    "backup_catchup": 12.0,
    "pending_drain": 6.0,
    "vacuum_analyze": 24.0,
}

Severity = Literal["warning", "critical"]


def now_utc() -> datetime:
    return datetime.now(UTC)


def coerce_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            return None
    return None


def hours_since(value: Any, *, now: datetime) -> float | None:
    dt = coerce_datetime(value)
    if dt is None:
        return None
    return round((now - dt).total_seconds() / 3600, 2)


def json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    return value


def severity_rank(value: Severity | str) -> int:
    return 2 if value == "critical" else 1


def status_from_severity(severity: Severity | None) -> str:
    if severity == "critical":
        return "critical"
    if severity == "warning":
        return "warning"
    return "ok"


def record_action(
    actions: list[dict[str, Any]],
    *,
    action_type: str,
    scope: str,
    fingerprint: str,
    status: str,
    detail: str,
    **extra: Any,
) -> None:
    action = {
        "type": action_type,
        "scope": scope,
        "fingerprint": fingerprint,
        "status": status,
        "detail": detail,
    }
    action.update(json_safe(extra))
    actions.append(action)


def normalize_action_status(value: Any) -> str:
    raw = str(value or "").lower()
    if raw in {"success", "completed"}:
        return "completed"
    if raw in {"completed_pending_upload", "partial"}:
        return "partial"
    if raw in {"idle", "skipped", "disabled"}:
        return "skipped"
    if raw in {"failed", "error"}:
        return "failed"
    return raw or "unknown"
