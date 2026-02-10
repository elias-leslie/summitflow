"""Agent enable/disable and selection operations."""

from __future__ import annotations

from .agent_configs import AgentConfig, get_agent_config, update_agent_config


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
    if agent_type == "gemini":
        return update_agent_config(project_id, {"gemini_enabled": enabled})
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
