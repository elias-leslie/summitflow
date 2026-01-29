"""Shared health check logic for Explorer entries.

Provides utilities for determining health status based on
various criteria (staleness, errors, completeness, etc.).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

HEALTH_CONFIG: dict[str, dict[str, Any]] = {
    "file": {
        "bloat_critical": "error",
        "bloat_warning": "warning",
        "stale_status": "warning",
        "health_flags_error": ["has_long_functions", "has_large_classes", "deep_nesting"],
    },
    "table": {
        "empty_table": "warning",
        "completeness_threshold": 50,
        "completeness_below": "warning",
        "freshness_error_days": 30,
        "freshness_warning_days": 7,
        "violations_error_threshold": 3,
        "violations_warning_threshold": 1,
    },
    "task": {
        "success_rate_error": 50,
        "success_rate_warning": 90,
        "unknown_schedule": "warning",
    },
    "endpoint": {
        "http_5xx": "error",
        "http_4xx_not_404": "error",
        "http_404": "warning",
        "orphaned": "warning",
    },
    "page": {
        "http_5xx": "error",
        "http_4xx_not_404": "error",
        "http_404": "warning",
        "console_errors": "warning",
    },
    "dependency": {
        "vuln_critical": "error",
        "vuln_high": "error",
        "vuln_medium": "warning",
        "is_outdated": "warning",
    },
}


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


def calculate_health_for_entry(entry_type: str, metadata: dict[str, Any]) -> str:
    """Calculate health status for an entry using type-specific config.

    Uses HEALTH_CONFIG to apply appropriate thresholds for each entry type.

    Args:
        entry_type: The type of entry (file, table, task, endpoint, page, dependency)
        metadata: Entry metadata dictionary

    Returns:
        Health status: 'healthy', 'warning', 'error', or 'unknown'
    """
    config = HEALTH_CONFIG.get(entry_type, {})

    if entry_type == "file":
        return _calculate_file_health(metadata, config)
    elif entry_type == "table":
        return _calculate_table_health(metadata, config)
    elif entry_type == "task":
        return _calculate_task_health(metadata, config)
    elif entry_type == "endpoint":
        return _calculate_endpoint_health(metadata, config)
    elif entry_type == "page":
        return _calculate_page_health(metadata, config)
    elif entry_type == "dependency":
        return _calculate_dependency_health(metadata, config)
    else:
        return "unknown"


def _calculate_file_health(metadata: dict[str, Any], config: dict[str, Any]) -> str:
    """Calculate health for file entries."""
    if metadata.get("is_directory"):
        return "healthy"

    bloat = metadata.get("bloat_level")
    if bloat == "critical":
        return str(config.get("bloat_critical", "error"))
    if bloat == "warning":
        return str(config.get("bloat_warning", "warning"))

    stale = metadata.get("stale_status")
    if stale == "stale":
        return str(config.get("stale_status", "warning"))

    health_flags = metadata.get("health_flags") or {}
    error_flags = config.get("health_flags_error", [])
    for flag in error_flags:
        if health_flags.get(flag):
            return "warning"

    return "healthy"


def _calculate_table_health(metadata: dict[str, Any], config: dict[str, Any]) -> str:
    """Calculate health for table entries."""
    row_count = metadata.get("row_count", 0)
    completeness = metadata.get("completeness_pct", 0)
    freshness_days = metadata.get("freshness_days")
    violations = metadata.get("violations", [])

    if row_count == 0:
        return str(config.get("empty_table", "warning"))

    threshold = int(config.get("completeness_threshold", 50))
    if completeness < threshold:
        return str(config.get("completeness_below", "warning"))

    if freshness_days is not None:
        error_days = int(config.get("freshness_error_days", 30))
        warning_days = int(config.get("freshness_warning_days", 7))
        if freshness_days > error_days:
            return "error"
        if freshness_days > warning_days:
            return "warning"

    if violations:
        error_threshold = int(config.get("violations_error_threshold", 3))
        warning_threshold = int(config.get("violations_warning_threshold", 1))
        if len(violations) >= error_threshold:
            return "error"
        if len(violations) >= warning_threshold:
            return "warning"

    return "healthy"


def _calculate_task_health(metadata: dict[str, Any], config: dict[str, Any]) -> str:
    """Calculate health for task entries."""
    success_rate = metadata.get("success_rate_pct")
    if success_rate is not None:
        error_threshold = int(config.get("success_rate_error", 50))
        warning_threshold = int(config.get("success_rate_warning", 90))
        if success_rate < error_threshold:
            return "error"
        if success_rate < warning_threshold:
            return "warning"

    schedule_type = metadata.get("schedule_type")
    if schedule_type == "unknown":
        return str(config.get("unknown_schedule", "warning"))

    return "healthy"


def _calculate_endpoint_health(metadata: dict[str, Any], config: dict[str, Any]) -> str:
    """Calculate health for endpoint entries."""
    http_status = metadata.get("http_status")

    if http_status is not None:
        if http_status >= 500:
            return str(config.get("http_5xx", "error"))
        if http_status >= 400 and http_status != 404:
            return str(config.get("http_4xx_not_404", "error"))
        if http_status == 404:
            return str(config.get("http_404", "warning"))

    depends_on = metadata.get("depends_on_tables", [])
    called_by = metadata.get("called_by_frontend", [])
    if not depends_on and not called_by:
        return str(config.get("orphaned", "warning"))

    return "healthy"


def _calculate_page_health(metadata: dict[str, Any], config: dict[str, Any]) -> str:
    """Calculate health for page entries."""
    http_status = metadata.get("http_status")
    console_errors = metadata.get("console_errors")

    if http_status is not None:
        if http_status >= 500:
            return str(config.get("http_5xx", "error"))
        if http_status >= 400 and http_status != 404:
            return str(config.get("http_4xx_not_404", "error"))
        if http_status == 404:
            return str(config.get("http_404", "warning"))

    if console_errors is not None and console_errors > 0:
        return str(config.get("console_errors", "warning"))

    return "healthy"


def _calculate_dependency_health(metadata: dict[str, Any], config: dict[str, Any]) -> str:
    """Calculate health for dependency entries."""
    vulns = metadata.get("vulnerabilities", {})
    critical = vulns.get("critical", 0)
    high = vulns.get("high", 0)
    medium = vulns.get("medium", 0)

    if critical > 0:
        return str(config.get("vuln_critical", "error"))
    if high > 0:
        return str(config.get("vuln_high", "error"))
    if medium > 0:
        return str(config.get("vuln_medium", "warning"))
    if metadata.get("is_outdated", False):
        return str(config.get("is_outdated", "warning"))

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
