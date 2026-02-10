"""Component source configuration for agent configs."""

from __future__ import annotations

from .agent_configs import AgentConfig, get_agent_config, update_agent_config

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
