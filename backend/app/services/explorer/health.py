"""Shared health check logic for Explorer entries.

Provides utilities for determining health status based on
various criteria (staleness, errors, completeness, etc.).
"""

from __future__ import annotations

from datetime import UTC, datetime

__all__ = [
    "calculate_bloat_level",
    "calculate_health",
    "calculate_staleness",
    "endpoint_health_from_status",
    "task_health_from_stats",
]


def calculate_health(
    *,
    error_count: int = 0,
    warning_count: int = 0,
    last_modified_days: int | None = None,
    completeness_pct: int | None = None,
    success_rate_pct: int | None = None,
    stale_threshold_days: int = 30,
    completeness_threshold: int = 80,
    success_rate_threshold: int = 95,
) -> str:
    """Calculate health status from multiple indicators.

    Priority: errors → warnings/thresholds → healthy

    Returns: 'healthy', 'warning', 'error', or 'unknown'
    """
    if error_count > 0:
        return "error"

    has_warnings = (
        warning_count > 0
        or (last_modified_days is not None and last_modified_days > stale_threshold_days)
        or (completeness_pct is not None and completeness_pct < completeness_threshold)
        or (success_rate_pct is not None and success_rate_pct < success_rate_threshold)
    )

    return "warning" if has_warnings else "healthy"


def calculate_staleness(last_modified: datetime | None, threshold_days: int = 30) -> str:
    """Determine staleness status from last modified timestamp.

    Returns: 'fresh', 'stale', or 'unknown'
    """
    if not last_modified:
        return "unknown"

    days_since = (datetime.now(UTC) - last_modified).days
    return "stale" if days_since > threshold_days else "fresh"


def calculate_bloat_level(
    size_bytes: int | None = None,
    lines_of_code: int | None = None,
    file_count: int | None = None,
    size_threshold_bytes: int = 100_000,  # 100KB
    loc_threshold: int = 1000,
    file_count_threshold: int = 50,
) -> str:
    """Determine bloat level for files/directories.

    Returns: 'ok', 'warning', 'critical', or 'unknown'
    """
    if size_bytes is None and lines_of_code is None and file_count is None:
        return "unknown"

    issues = 0

    if size_bytes is not None:
        if size_bytes > size_threshold_bytes * 5:
            issues += 2
        elif size_bytes > size_threshold_bytes:
            issues += 1

    if lines_of_code is not None:
        if lines_of_code > loc_threshold * 3:
            issues += 2
        elif lines_of_code > loc_threshold:
            issues += 1

    if file_count is not None:
        if file_count > file_count_threshold * 3:
            issues += 2
        elif file_count > file_count_threshold:
            issues += 1

    if issues >= 3:
        return "critical"
    return "warning" if issues >= 1 else "ok"


def endpoint_health_from_status(
    http_status: int | None,
    console_errors: int = 0,
    response_time_ms: int | None = None,
    slow_threshold_ms: int = 3000,
) -> str:
    """Determine endpoint health from HTTP status and metrics.

    Returns: 'healthy', 'warning', 'error', or 'unknown'
    """
    if http_status is None:
        return "unknown"

    if http_status >= 500 or (http_status >= 400 and http_status != 404) or console_errors > 0:
        return "error"

    is_slow = response_time_ms is not None and response_time_ms > slow_threshold_ms
    if http_status == 404 or (300 <= http_status < 400) or is_slow:
        return "warning"

    return "healthy"


def task_health_from_stats(
    success_count: int,
    failure_count: int,
    last_run_at: datetime | None = None,
    expected_interval_minutes: int | None = None,
) -> str:
    """Determine task health from execution statistics.

    Returns: 'healthy', 'warning', 'error', or 'unknown'
    """
    total = success_count + failure_count
    if total == 0:
        return "unknown"

    success_rate = (success_count / total) * 100

    if success_rate < 80:
        return "error"
    if success_rate < 95:
        return "warning"

    if expected_interval_minutes and last_run_at:
        minutes_since = (datetime.now(UTC) - last_run_at).total_seconds() / 60
        if minutes_since > expected_interval_minutes * 2:
            return "warning"

    return "healthy"
