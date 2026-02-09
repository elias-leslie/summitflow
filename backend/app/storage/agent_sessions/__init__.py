"""Agent sessions storage layer - Build session tracking.

This module provides data access for agent build session tracking.
"""

from __future__ import annotations

# Re-export all public functions
from .build_state import (
    get_build_state,
    merge_build_state,
    update_build_state,
)
from .core import (
    create_session,
    end_session,
    fail_session,
    get_recent_sessions,
    get_session,
    get_session_by_id,
    increment_test_counts,
    list_sessions,
    update_session,
)

__all__ = [
    "create_session",
    "end_session",
    "fail_session",
    "get_build_state",
    "get_recent_sessions",
    "get_session",
    "get_session_by_id",
    "increment_test_counts",
    "list_sessions",
    "merge_build_state",
    "update_build_state",
    "update_session",
]
