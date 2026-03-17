"""Explorer storage layer - ALL database operations for explorer.

This module acts as an orchestrator that re-exports functions from specialized modules:

- explorer_entries: Core CRUD operations for explorer_entries table
- explorer_analysis: Analysis and refactoring target queries
- explorer_scan_state: Scan state persistence
- explorer_symbols: Symbol-level precision retrieval rows

Per architecture: No other module should contain direct explorer DB queries.
"""

from __future__ import annotations

# Re-export from explorer_analysis
from .explorer_analysis import (
    REFACTOR_EXCLUDE_PATTERNS,
    REFACTORABLE_EXTENSIONS,
    count_stale_metadata_entries,
    get_coverage_gaps,
    get_refactor_targets,
)

# Re-export from explorer_entries (core CRUD)
from .explorer_entries import (
    cleanup_stale_entries,
    delete_entries,
    get_children,
    get_entries,
    get_entry,
    get_entry_by_id,
    get_scan_metrics,
    get_stats,
    get_type_summaries,
    upsert_entries,
)

# Re-export from explorer_scan_state
from .explorer_scan_state import (
    get_scan_state,
    update_scan_state,
)
from .explorer_symbols import (
    cleanup_stale_symbols,
    get_symbol,
    get_symbol_stats,
    list_related_entries_for_file,
    list_symbols_for_file,
    replace_file_symbols,
    search_symbols,
    summarize_symbols_for_file,
)

__all__ = [
    "REFACTORABLE_EXTENSIONS",
    "REFACTOR_EXCLUDE_PATTERNS",
    "cleanup_stale_entries",
    "cleanup_stale_symbols",
    "count_stale_metadata_entries",
    "delete_entries",
    "get_children",
    "get_coverage_gaps",
    "get_entries",
    "get_entry",
    "get_entry_by_id",
    "get_refactor_targets",
    "get_scan_metrics",
    "get_scan_state",
    "get_stats",
    "get_symbol",
    "get_symbol_stats",
    "get_type_summaries",
    "list_related_entries_for_file",
    "list_symbols_for_file",
    "replace_file_symbols",
    "search_symbols",
    "summarize_symbols_for_file",
    "update_scan_state",
    "upsert_entries",
]
