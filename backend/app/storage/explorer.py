"""Explorer storage layer - ALL database operations for explorer.

This module acts as an orchestrator that re-exports functions from specialized modules:

- explorer_entries: Core CRUD operations for explorer_entries table
- explorer_analysis: Analysis and refactoring target queries

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
    _ALLOWED_SORT_FIELDS,
    _ENTRY_COLUMNS,
    cleanup_stale_entries,
    delete_entries,
    get_children,
    get_entries,
    get_entry,
    get_entry_by_id,
    get_stats,
    upsert_entries,
)

__all__ = [
    "REFACTORABLE_EXTENSIONS",
    "REFACTOR_EXCLUDE_PATTERNS",
    "_ALLOWED_SORT_FIELDS",
    "_ENTRY_COLUMNS",
    "cleanup_stale_entries",
    "count_stale_metadata_entries",
    "delete_entries",
    "get_children",
    "get_coverage_gaps",
    "get_entries",
    "get_entry",
    "get_entry_by_id",
    "get_refactor_targets",
    "get_stats",
    "upsert_entries",
]
