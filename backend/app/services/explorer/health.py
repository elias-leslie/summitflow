"""Shared health check logic for Explorer entries.

Provides utilities for determining health status based on
various criteria (staleness, errors, completeness, etc.).
"""

from __future__ import annotations

from datetime import UTC, datetime


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

    Priority order:
    1. Errors present → 'error'
    2. Warnings present or thresholds exceeded → 'warning'
    3. All good → 'healthy'

    Args:
        error_count: Number of errors
        warning_count: Number of warnings
        last_modified_days: Days since last modification (None = unknown)
        completeness_pct: Data completeness percentage (None = unknown)
        success_rate_pct: Success rate percentage (None = unknown)
        stale_threshold_days: Days before content is considered stale
        completeness_threshold: Minimum completeness % for healthy
        success_rate_threshold: Minimum success rate % for healthy

    Returns:
        Health status: 'healthy', 'warning', 'error', or 'unknown'
    """
    # Error state
    if error_count > 0:
        return "error"

    # Warning states
    warnings = []

    if warning_count > 0:
        warnings.append("warnings")

    if last_modified_days is not None and last_modified_days > stale_threshold_days:
        warnings.append("stale")

    if completeness_pct is not None and completeness_pct < completeness_threshold:
        warnings.append("incomplete")

    if success_rate_pct is not None and success_rate_pct < success_rate_threshold:
        warnings.append("low_success")

    if warnings:
        return "warning"

    return "healthy"


def calculate_staleness(last_modified: datetime | None, threshold_days: int = 30) -> str:
    """Determine staleness status from last modified timestamp.

    Args:
        last_modified: Last modification datetime (UTC)
        threshold_days: Days before content is considered stale

    Returns:
        'fresh', 'stale', or 'unknown'
    """
    if not last_modified:
        return "unknown"

    now = datetime.now(UTC)
    days_since = (now - last_modified).days

    if days_since > threshold_days:
        return "stale"
    return "fresh"


def calculate_bloat_level(
    size_bytes: int | None = None,
    lines_of_code: int | None = None,
    file_count: int | None = None,
    size_threshold_bytes: int = 100_000,  # 100KB
    loc_threshold: int = 1000,
    file_count_threshold: int = 50,
) -> str:
    """Determine bloat level for files/directories.

    Args:
        size_bytes: Total size in bytes
        lines_of_code: Total lines of code
        file_count: Number of files (for directories)
        size_threshold_bytes: Size threshold for warning
        loc_threshold: LOC threshold for warning
        file_count_threshold: File count threshold for warning

    Returns:
        'ok', 'warning', 'critical', or 'unknown'
    """
    if size_bytes is None and lines_of_code is None and file_count is None:
        return "unknown"

    issues = 0

    if size_bytes is not None and size_bytes > size_threshold_bytes:
        issues += 1
        if size_bytes > size_threshold_bytes * 5:
            issues += 1

    if lines_of_code is not None and lines_of_code > loc_threshold:
        issues += 1
        if lines_of_code > loc_threshold * 3:
            issues += 1

    if file_count is not None and file_count > file_count_threshold:
        issues += 1
        if file_count > file_count_threshold * 3:
            issues += 1

    if issues >= 3:
        return "critical"
    if issues >= 1:
        return "warning"
    return "ok"


def endpoint_health_from_status(
    http_status: int | None,
    console_errors: int = 0,
    response_time_ms: int | None = None,
    slow_threshold_ms: int = 3000,
) -> str:
    """Determine endpoint health from HTTP status and metrics.

    Args:
        http_status: HTTP response status code
        console_errors: Number of console errors
        response_time_ms: Response time in milliseconds
        slow_threshold_ms: Threshold for slow response warning

    Returns:
        Health status: 'healthy', 'warning', 'error', or 'unknown'
    """
    if http_status is None:
        return "unknown"

    # Error status codes
    if http_status >= 500:
        return "error"

    # Client errors (excluding 404 which might be expected)
    if http_status >= 400 and http_status != 404:
        return "error"

    # Console errors always indicate issues
    if console_errors > 0:
        return "error"

    # Slow response
    if response_time_ms is not None and response_time_ms > slow_threshold_ms:
        return "warning"

    # 404 as warning (might need attention)
    if http_status == 404:
        return "warning"

    # Redirect as warning
    if 300 <= http_status < 400:
        return "warning"

    return "healthy"


def task_health_from_stats(
    success_count: int,
    failure_count: int,
    last_run_at: datetime | None = None,
    expected_interval_minutes: int | None = None,
) -> str:
    """Determine task health from execution statistics.

    Args:
        success_count: Number of successful executions (e.g., in last 7 days)
        failure_count: Number of failed executions
        last_run_at: Last run timestamp
        expected_interval_minutes: Expected run interval (for detecting stale tasks)

    Returns:
        Health status: 'healthy', 'warning', 'error', or 'unknown'
    """
    total = success_count + failure_count

    if total == 0:
        return "unknown"

    # Calculate success rate
    success_rate = (success_count / total) * 100

    if success_rate < 80:
        return "error"

    if success_rate < 95:
        return "warning"

    # Check for stale task if expected interval is set
    if expected_interval_minutes and last_run_at:
        now = datetime.now(UTC)
        minutes_since = (now - last_run_at).total_seconds() / 60

        # If more than 2x the expected interval has passed, warn
        if minutes_since > expected_interval_minutes * 2:
            return "warning"

    return "healthy"
