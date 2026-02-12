"""Storage layer for agent configurations per project."""

from __future__ import annotations

import logging
from typing import TypedDict, cast

from psycopg.types.json import Jsonb

from ..constants import DEFAULT_CLAUDE_MODEL, DEFAULT_GEMINI_MODEL
from .connection import get_connection

logger = logging.getLogger(__name__)


class AgentConfig(TypedDict, total=False):
    """Agent configuration for a project."""

    claude_enabled: bool
    gemini_enabled: bool
    default_agent: str  # "claude" or "gemini"
    claude_model: str  # "claude-sonnet-4-5", "claude-opus-4-5", "claude-haiku-4-5"
    gemini_model: str  # "gemini-3-flash-preview", "gemini-3-pro-preview"

    # Component management
    component_source: str  # "pages", "endpoints", "directories", or "manual"

    # Autonomous execution controls
    autonomous_enabled: bool  # Enable autonomous task pickup and execution
    autonomous_start_hour: int  # Hour (0-23) when autonomous execution can start
    autonomous_end_hour: int  # Hour (0-23) when autonomous execution must stop
    autonomous_max_concurrent: int  # Max concurrent autonomous tasks (1-3)


DEFAULT_AGENT_CONFIG: AgentConfig = {
    "claude_enabled": True,
    "gemini_enabled": True,
    "default_agent": "gemini",
    "claude_model": DEFAULT_CLAUDE_MODEL,
    "gemini_model": DEFAULT_GEMINI_MODEL,
    # Component management
    "component_source": "manual",
    # Autonomous execution - disabled by default (opt-in)
    "autonomous_enabled": False,
    "autonomous_start_hour": 0,  # Default: 24/7 execution allowed
    "autonomous_end_hour": 24,  # 24 means end of day (midnight)
    "autonomous_max_concurrent": 1,  # Default: 1 concurrent task
}


def get_agent_config(project_id: str) -> AgentConfig:
    """Get agent configuration for a project.

    Args:
        project_id: Project ID

    Returns:
        AgentConfig dict, or default config if not set
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
                SELECT agent_configs
                FROM projects
                WHERE id = %s
                """,
            (project_id,),
        )
        row = cur.fetchone()

        if row is None:
            logger.warning(f"Project {project_id} not found, returning default config")
            return DEFAULT_AGENT_CONFIG.copy()

        config = row[0]
        if config is None:
            return DEFAULT_AGENT_CONFIG.copy()

        # Merge with defaults for any missing keys
        result = DEFAULT_AGENT_CONFIG.copy()
        result.update(config)
        return result


def update_agent_config(project_id: str, config: AgentConfig) -> AgentConfig:
    """Update agent configuration for a project.

    Args:
        project_id: Project ID
        config: Partial config to update (only provided fields are updated)

    Returns:
        Updated full config

    Raises:
        ValueError: If project not found
    """
    # Get current config
    current = get_agent_config(project_id)

    # Merge with new values
    current.update(config)

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
                UPDATE projects
                SET agent_configs = %s
                WHERE id = %s
                RETURNING agent_configs
                """,
            (Jsonb(current), project_id),
        )
        row = cur.fetchone()

        if row is None:
            raise ValueError(f"Project {project_id} not found")

        conn.commit()
        # psycopg3 JSONB returns dict that matches AgentConfig structure
        return cast(AgentConfig, row[0])


# Re-export submodule functions for backward compatibility
# These imports are at the end to avoid circular dependencies
from .agent_configs_agents import (  # noqa: E402
    enable_agent,
    get_enabled_agents,
    set_default_agent,
)
from .agent_configs_autonomous import (  # noqa: E402
    AutonomousScheduleConfig,
    get_allowed_task_types,
    get_auto_merge_enabled,
    get_autonomous_schedule,
    get_cooldown_minutes,
    get_max_extensions,
    get_max_self_fix_attempts,
    get_max_supervisor_attempts,
    get_max_tasks_per_day,
    get_preferred_model_tier,
    get_require_review,
    is_autonomous_enabled,
    is_within_autonomous_hours,
    update_autonomous_schedule,
)
from .agent_configs_components import (  # noqa: E402
    COMPONENT_SOURCES,
    get_component_source,
    set_component_source,
)

__all__ = [
    "COMPONENT_SOURCES",
    "DEFAULT_AGENT_CONFIG",
    "AgentConfig",
    "AutonomousScheduleConfig",
    "enable_agent",
    "get_agent_config",
    "get_autonomous_schedule",
    "get_component_source",
    "get_enabled_agents",
    "is_autonomous_enabled",
    "is_within_autonomous_hours",
    "set_component_source",
    "set_default_agent",
    "update_agent_config",
    "update_autonomous_schedule",
]
