"""Explorer storage layer - ALL database operations for explorer.

This module acts as an orchestrator that re-exports functions from specialized modules:

- explorer_entries: Core CRUD operations for explorer_entries table
- explorer_capability_links: Link management between entries and capabilities
- explorer_analysis: Analysis and refactoring target queries
- explorer_scan_state: Scan state persistence

Per architecture: No other module should contain direct explorer DB queries.
"""

from __future__ import annotations

# Re-export from explorer_analysis
from .explorer_analysis import (
    REFACTOR_EXCLUDE_PATTERNS,
    REFACTORABLE_EXTENSIONS,
    count_stale_metadata_entries,
    get_coverage_gaps,
    get_multi_capability_files,
    get_refactor_targets,
)

# Re-export from explorer_capability_links
from .explorer_capability_links import (
    create_capability_link,
    delete_capability_link,
    get_capability_links,
    get_entry_capabilities,
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

# Re-export from explorer_scan_state
from .explorer_scan_state import (
    get_scan_state,
    update_scan_state,
)

__all__ = [
    "REFACTORABLE_EXTENSIONS",
    "REFACTOR_EXCLUDE_PATTERNS",
    "_ALLOWED_SORT_FIELDS",
    # Constants
    "_ENTRY_COLUMNS",
    # Entry CRUD
    "cleanup_stale_entries",
    # Analysis
    "count_stale_metadata_entries",
    # Capability links
    "create_capability_link",
    "delete_capability_link",
    "delete_entries",
    "get_capability_links",
    "get_children",
    "get_coverage_gaps",
    "get_entries",
    "get_entry",
    "get_entry_by_id",
    "get_entry_capabilities",
    "get_multi_capability_files",
    "get_refactor_targets",
    # Scan state
    "get_scan_state",
    "get_stats",
    "update_scan_state",
    "upsert_entries",
]
