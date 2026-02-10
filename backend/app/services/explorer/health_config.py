"""Health check configuration for Explorer entries.

Defines thresholds and severity levels for each entry type.
"""

from __future__ import annotations

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
    "architecture": {
        "parallel_implementation_threshold": 1,
        "missing_infrastructure_threshold": 3,
        "duplicate_utility_threshold": 5,
        "error_count_threshold": 1,
        "warning_count_threshold": 3,
    },
}
