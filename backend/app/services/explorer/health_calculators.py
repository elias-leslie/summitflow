"""Type-specific health calculators for Explorer entries.

Each function calculates health for a specific entry type using
type-specific configuration and metadata.
"""

from __future__ import annotations

from typing import Any


def calculate_file_health(metadata: dict[str, Any], config: dict[str, Any]) -> str:
    """Calculate health for file entries.

    Args:
        metadata: File entry metadata
        config: Configuration for file health checks

    Returns:
        Health status: 'healthy', 'warning', or 'error'
    """
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


def calculate_table_health(metadata: dict[str, Any], config: dict[str, Any]) -> str:
    """Calculate health for table entries.

    Args:
        metadata: Table entry metadata
        config: Configuration for table health checks

    Returns:
        Health status: 'healthy', 'warning', or 'error'
    """
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


def calculate_task_health(metadata: dict[str, Any], config: dict[str, Any]) -> str:
    """Calculate health for task entries.

    Args:
        metadata: Task entry metadata
        config: Configuration for task health checks

    Returns:
        Health status: 'healthy', 'warning', or 'error'
    """
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


def calculate_endpoint_health(metadata: dict[str, Any], config: dict[str, Any]) -> str:
    """Calculate health for endpoint entries.

    Args:
        metadata: Endpoint entry metadata
        config: Configuration for endpoint health checks

    Returns:
        Health status: 'healthy', 'warning', or 'error'
    """
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


def calculate_page_health(metadata: dict[str, Any], config: dict[str, Any]) -> str:
    """Calculate health for page entries.

    Args:
        metadata: Page entry metadata
        config: Configuration for page health checks

    Returns:
        Health status: 'healthy', 'warning', or 'error'
    """
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


def calculate_dependency_health(metadata: dict[str, Any], config: dict[str, Any]) -> str:
    """Calculate health for dependency entries.

    Args:
        metadata: Dependency entry metadata
        config: Configuration for dependency health checks

    Returns:
        Health status: 'healthy', 'warning', or 'error'
    """
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


def calculate_architecture_health(metadata: dict[str, Any], config: dict[str, Any]) -> str:
    """Calculate health for architecture entries.

    Based on violation counts by type:
    - parallel_implementation: Multiple implementations of same functionality (error)
    - missing_infrastructure: Missing caching, error handling, observability (warning)
    - duplicate_utility: Literal code duplication (warning)

    Args:
        metadata: Architecture entry metadata
        config: Configuration for architecture health checks

    Returns:
        Health status: 'healthy', 'warning', or 'error'
    """
    violations = metadata.get("violations", [])

    parallel_count = 0
    missing_count = 0
    duplicate_count = 0

    for v in violations:
        vtype = v.get("violation_type", "")
        if vtype == "parallel_implementation":
            parallel_count += 1
        elif vtype == "missing_infrastructure":
            missing_count += 1
        elif vtype == "duplicate_utility":
            duplicate_count += 1

    parallel_threshold = int(config.get("parallel_implementation_threshold", 1))
    if parallel_count >= parallel_threshold:
        return "error"

    error_threshold = int(config.get("error_count_threshold", 1))
    total_errors = sum(1 for v in violations if v.get("severity") == "error")
    if total_errors >= error_threshold:
        return "error"

    missing_threshold = int(config.get("missing_infrastructure_threshold", 3))
    duplicate_threshold = int(config.get("duplicate_utility_threshold", 5))
    warning_threshold = int(config.get("warning_count_threshold", 3))

    if missing_count >= missing_threshold:
        return "warning"
    if duplicate_count >= duplicate_threshold:
        return "warning"

    total_warnings = sum(1 for v in violations if v.get("severity") == "warning")
    if total_warnings >= warning_threshold:
        return "warning"

    return "healthy"
