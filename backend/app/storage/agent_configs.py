"""Storage layer for agent configurations per project."""

from __future__ import annotations

import json
import logging
from typing import Any, TypedDict

from psycopg.types.json import Jsonb

from .connection import get_connection

logger = logging.getLogger(__name__)


class AgentConfig(TypedDict, total=False):
    """Agent configuration for a project."""

    claude_enabled: bool
    gemini_enabled: bool
    default_agent: str  # "claude" or "gemini"
    claude_model: str  # "claude-sonnet-4-5", "claude-opus-4-5", "claude-haiku-4-5"
    gemini_model: str  # "gemini-3-flash-preview", "gemini-3-pro-preview"


DEFAULT_AGENT_CONFIG: AgentConfig = {
    "claude_enabled": True,
    "gemini_enabled": True,
    "default_agent": "gemini",
    "claude_model": "claude-sonnet-4-5",
    "gemini_model": "gemini-3-flash-preview",
}


def get_agent_config(project_id: str) -> AgentConfig:
    """Get agent configuration for a project.

    Args:
        project_id: Project ID

    Returns:
        AgentConfig dict, or default config if not set
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
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

    with get_connection() as conn:
        with conn.cursor() as cur:
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
            return row[0]


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
