"""Scan history storage - Track scan executions with trigger metadata.

This module handles:
- Recording scan start (with trigger metadata)
- Recording scan completion (with metrics and delta calculation)
- Querying scan history and sparkline data
- Computing before/after scan comparisons
"""

from __future__ import annotations

from ._helpers import row_to_scan as _row_to_scan
from ._reads import get_scan_comparison, get_scan_history, get_sparkline_data, get_summary
from ._writes import record_scan_complete, record_scan_start

__all__ = [
    "_row_to_scan",
    "get_scan_comparison",
    "get_scan_history",
    "get_sparkline_data",
    "get_summary",
    "record_scan_complete",
    "record_scan_start",
]
