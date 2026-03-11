"""Scan history storage - Track scan executions with trigger metadata.

This module handles:
- Recording scan start (with trigger metadata)
- Recording scan completion (with metrics and delta calculation)
- Querying scan history and sparkline data
- Computing before/after scan comparisons
"""

from __future__ import annotations

from ._maintenance import cleanup_old_scan_history, fail_stale_running_scans
from ._reads import (
    get_latest_scan,
    get_scan_comparison,
    get_scan_history,
    get_sparkline_data,
    get_summary,
)
from ._writes import record_scan_complete, record_scan_start

__all__ = [
    "cleanup_old_scan_history",
    "fail_stale_running_scans",
    "get_latest_scan",
    "get_scan_comparison",
    "get_scan_history",
    "get_sparkline_data",
    "get_summary",
    "record_scan_complete",
    "record_scan_start",
]
