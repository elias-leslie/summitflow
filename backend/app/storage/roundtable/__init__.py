"""Roundtable session storage - Persistence for multi-agent chat sessions.

This package provides data access for roundtable sessions including
messages, specs, and configuration settings.
"""

# Session CRUD operations
# Message and feature operations
from .messages import (
    add_message_to_session,
    update_generated_features,
)
from .sessions import (
    delete_oldest_session,
    delete_session,
    get_session_count,
    list_sessions,
    load_session,
    save_session,
)

# Settings and configuration operations
from .settings import (
    increment_tool_stats,
    update_agent_config,
    update_sdk_session_ids,
    update_session_metadata,
    update_tool_stats,
    update_tools_enabled,
    update_tools_settings,
)

# TDD spec operations
from .specs import (
    get_generated_spec,
    update_generated_spec,
)

__all__ = [
    # Messages
    "add_message_to_session",
    # Sessions
    "delete_oldest_session",
    "delete_session",
    # Specs
    "get_generated_spec",
    "get_session_count",
    # Settings
    "increment_tool_stats",
    "list_sessions",
    "load_session",
    "save_session",
    "update_agent_config",
    "update_generated_features",
    "update_generated_spec",
    "update_sdk_session_ids",
    "update_session_metadata",
    "update_tool_stats",
    "update_tools_enabled",
    "update_tools_settings",
]
