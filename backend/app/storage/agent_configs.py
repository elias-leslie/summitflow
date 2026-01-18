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


def set_default_agent(project_id: str, agent_type: str) -> AgentConfig:
    """Set the default agent for a project.

    Args:
        project_id: Project ID
        agent_type: "claude" or "gemini"

    Returns:
        Updated config

    Raises:
        ValueError: If invalid agent type
    """
    if agent_type not in ("claude", "gemini"):
        raise ValueError(f"Invalid agent type: {agent_type}. Use 'claude' or 'gemini'.")

    return update_agent_config(project_id, {"default_agent": agent_type})


def enable_agent(project_id: str, agent_type: str, enabled: bool = True) -> AgentConfig:
    """Enable or disable an agent for a project.

    Args:
        project_id: Project ID
        agent_type: "claude" or "gemini"
        enabled: Whether to enable

    Returns:
        Updated config

    Raises:
        ValueError: If invalid agent type
    """
    if agent_type == "claude":
        return update_agent_config(project_id, {"claude_enabled": enabled})
    elif agent_type == "gemini":
        return update_agent_config(project_id, {"gemini_enabled": enabled})
    else:
        raise ValueError(f"Invalid agent type: {agent_type}. Use 'claude' or 'gemini'.")


def get_enabled_agents(project_id: str) -> list[str]:
    """Get list of enabled agents for a project.

    Args:
        project_id: Project ID

    Returns:
        List of enabled agent types (e.g., ["claude", "gemini"])
    """
    config = get_agent_config(project_id)
    enabled = []
    if config.get("claude_enabled", True):
        enabled.append("claude")
    if config.get("gemini_enabled", True):
        enabled.append("gemini")
    return enabled


# Valid component source values
COMPONENT_SOURCES = frozenset(["pages", "endpoints", "directories", "manual"])


def get_component_source(project_id: str) -> str:
    """Get the component source setting for a project.

    Args:
        project_id: Project ID

    Returns:
        Component source: 'pages', 'endpoints', 'directories', or 'manual'
    """
    config = get_agent_config(project_id)
    source = config.get("component_source", "manual")
    if source not in COMPONENT_SOURCES:
        return "manual"
    return source


def set_component_source(project_id: str, source: str) -> AgentConfig:
    """Set the component source for a project.

    Args:
        project_id: Project ID
        source: One of 'pages', 'endpoints', 'directories', 'manual'

    Returns:
        Updated config

    Raises:
        ValueError: If invalid source value
    """
    if source not in COMPONENT_SOURCES:
        raise ValueError(
            f"Invalid component source: {source}. "
            f"Use one of: {', '.join(sorted(COMPONENT_SOURCES))}"
        )

    return update_agent_config(project_id, {"component_source": source})


def is_autonomous_enabled(project_id: str) -> bool:
    """Check if autonomous execution is enabled for a project.

    Args:
        project_id: Project ID

    Returns:
        True if autonomous execution is enabled
    """
    config = get_agent_config(project_id)
    return bool(config.get("autonomous_enabled", False))


class AutonomousScheduleConfig(TypedDict):
    """Autonomous execution schedule configuration."""

    enabled: bool
    start_hour: int  # 0-23
    end_hour: int  # 1-24 (24 = end of day)
    max_concurrent: int  # 1-3


def get_autonomous_schedule(project_id: str) -> AutonomousScheduleConfig:
    """Get autonomous execution schedule for a project.

    Args:
        project_id: Project ID

    Returns:
        AutonomousScheduleConfig with schedule settings
    """
    config = get_agent_config(project_id)
    return {
        "enabled": config.get("autonomous_enabled", False),
        "start_hour": config.get("autonomous_start_hour", 0),
        "end_hour": config.get("autonomous_end_hour", 24),
        "max_concurrent": config.get("autonomous_max_concurrent", 1),
    }


def is_within_autonomous_hours(project_id: str, current_hour: int) -> bool:
    """Check if current hour is within the autonomous execution window.

    Args:
        project_id: Project ID
        current_hour: Current hour (0-23)

    Returns:
        True if current_hour is within [start_hour, end_hour)
    """
    schedule = get_autonomous_schedule(project_id)
    if not schedule["enabled"]:
        return False

    start = schedule["start_hour"]
    end = schedule["end_hour"]

    # Handle wrap-around (e.g., 22:00 to 06:00)
    if start < end:
        # Normal range: 8-18 means 8:00 to 17:59
        return start <= current_hour < end
    else:
        # Wrap-around: 22-6 means 22:00-23:59 or 00:00-05:59
        return current_hour >= start or current_hour < end


def update_autonomous_schedule(
    project_id: str,
    start_hour: int | None = None,
    end_hour: int | None = None,
    max_concurrent: int | None = None,
) -> AgentConfig:
    """Update autonomous execution schedule for a project.

    Args:
        project_id: Project ID
        start_hour: Hour (0-23) when execution can start
        end_hour: Hour (1-24) when execution must stop
        max_concurrent: Max concurrent tasks (1-3)

    Returns:
        Updated config

    Raises:
        ValueError: If invalid values provided
    """
    updates: AgentConfig = {}

    if start_hour is not None:
        if not 0 <= start_hour <= 23:
            raise ValueError("start_hour must be 0-23")
        updates["autonomous_start_hour"] = start_hour

    if end_hour is not None:
        if not 1 <= end_hour <= 24:
            raise ValueError("end_hour must be 1-24")
        updates["autonomous_end_hour"] = end_hour

    if max_concurrent is not None:
        if not 1 <= max_concurrent <= 3:
            raise ValueError("max_concurrent must be 1-3")
        updates["autonomous_max_concurrent"] = max_concurrent

    return update_agent_config(project_id, updates)
