"""Memory storage layer - Re-exports for backward compatibility.

This module re-exports functions from specialized sub-modules:
- memory_observations.py: Observation CRUD
- memory_checkpoints.py: Checkpoint CRUD
- memory_diary.py: Session diary management
- memory_embeddings.py: Embedding and semantic search
- memory_health.py: Memory system health metrics
- memory_patterns.py: Pattern CRUD
- memory_queue.py: Observation queue management
- memory_utils.py: Shared utilities
"""

from __future__ import annotations

# Re-export checkpoint functions
from .memory_checkpoints import (
    CheckpointDict,
    cleanup_old_checkpoints,
    create_checkpoint,
    delete_checkpoint,
    get_latest_checkpoint,
    list_checkpoints,
)

# Re-export diary functions
from .memory_diary import (
    count_diary_entries,
    count_diary_entries_since,
    create_diary_entry,
    get_diary_entry,
    get_diary_entry_by_session,
    get_projects_needing_reflection,
    get_unreflected_diary_count,
    list_diary_entries,
    mark_diary_entries_reflected,
)

# Re-export embedding functions
from .memory_embeddings import (
    has_embeddings,
    search_observations_semantic,
)

# Re-export health functions
from .memory_health import get_lifecycle_stats

# Re-export observation functions
from .memory_observations import (
    ObservationDict,
    count_observations,
    count_observations_since,
    create_observation,
    get_observation,
    get_observations_by_session,
    list_observations,
    query_observations,
    search_observations_fts,
)

# Re-export pattern functions
from .memory_patterns import (
    count_patterns,
    create_pattern,
    get_pattern,
    get_stale_patterns,
    increment_pattern_usage,
    list_patterns,
    mark_pattern_applied,
    update_pattern_feedback,
    update_pattern_status,
)

# Re-export queue functions
from .memory_queue import (
    archive_failed_queue_items,
    create_queue_item,
    get_pending_queue_items,
    reset_stuck_queue_items,
    update_queue_item_status,
)

__all__ = [
    "CheckpointDict",
    "ObservationDict",
    "archive_failed_queue_items",
    "cleanup_old_checkpoints",
    "count_diary_entries",
    "count_diary_entries_since",
    "count_observations",
    "count_observations_since",
    "count_patterns",
    "create_checkpoint",
    "create_diary_entry",
    "create_observation",
    "create_pattern",
    "create_queue_item",
    "delete_checkpoint",
    "get_diary_entry",
    "get_diary_entry_by_session",
    "get_latest_checkpoint",
    "get_lifecycle_stats",
    "get_observation",
    "get_observations_by_session",
    "get_pattern",
    "get_pending_queue_items",
    "get_projects_needing_reflection",
    "get_stale_patterns",
    "get_unreflected_diary_count",
    "has_embeddings",
    "increment_pattern_usage",
    "list_checkpoints",
    "list_diary_entries",
    "list_observations",
    "list_patterns",
    "mark_diary_entries_reflected",
    "mark_pattern_applied",
    "query_observations",
    "reset_stuck_queue_items",
    "search_observations_fts",
    "search_observations_semantic",
    "update_pattern_feedback",
    "update_pattern_status",
    "update_queue_item_status",
]
