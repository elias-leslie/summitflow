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

    # Memory system controls
    memory_enabled: bool  # Master switch - disables all memory when false
    observations_enabled: bool  # Tool observation capture
    diary_enabled: bool  # Session diary entries
    patterns_enabled: bool  # Pattern detection
    checkpoints_enabled: bool  # Session checkpoints
    context_injection_enabled: bool  # Auto-inject context at session start

    # Component management
    component_source: str  # "pages", "endpoints", "directories", or "manual"

    # Autonomous execution controls
    autonomous_enabled: bool  # Enable autonomous task pickup and execution

    # Extraction throttle controls
    extraction_enabled: bool  # Master kill switch for AI extraction
    extraction_rpm_limit: int  # Requests per minute limit (0=disabled, 60=unlimited)


DEFAULT_AGENT_CONFIG: AgentConfig = {
    "claude_enabled": True,
    "gemini_enabled": True,
    "default_agent": "gemini",
    "claude_model": DEFAULT_CLAUDE_MODEL,
    "gemini_model": DEFAULT_GEMINI_MODEL,
    # Memory defaults - all enabled for backward compatibility
    "memory_enabled": True,
    "observations_enabled": True,
    "diary_enabled": True,
    "patterns_enabled": True,
    "checkpoints_enabled": True,
    "context_injection_enabled": True,
    # Component management
    "component_source": "manual",
    # Autonomous execution - disabled by default (opt-in)
    "autonomous_enabled": False,
    # Extraction throttle - enabled, default 10 RPM (lean and mean)
    "extraction_enabled": True,
    "extraction_rpm_limit": 10,
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


# Valid memory feature names for is_memory_feature_enabled
MEMORY_FEATURES = frozenset(
    ["observations", "diary", "patterns", "checkpoints", "context_injection"]
)


def is_memory_feature_enabled(project_id: str, feature: str) -> bool:
    """Check if a specific memory feature is enabled for a project.

    Uses master switch pattern: if memory_enabled=false, all features are disabled.
    Otherwise, checks the feature-specific flag.

    Args:
        project_id: Project ID
        feature: One of 'observations', 'diary', 'patterns', 'checkpoints', 'context_injection'

    Returns:
        True if the feature is enabled, False otherwise
    """
    if feature not in MEMORY_FEATURES:
        logger.warning(f"Unknown memory feature: {feature}")
        return True  # Default to enabled for unknown features

    config = get_agent_config(project_id)

    # Master switch check
    if not config.get("memory_enabled", True):
        return False

    # Feature-specific check
    feature_key = f"{feature}_enabled"
    return bool(config.get(feature_key, True))


def get_memory_config(project_id: str) -> dict[str, bool]:
    """Get all memory configuration flags for a project.

    Args:
        project_id: Project ID

    Returns:
        Dict with all memory flags:
        {
            'memory_enabled': bool,
            'observations_enabled': bool,
            'diary_enabled': bool,
            'patterns_enabled': bool,
            'checkpoints_enabled': bool,
            'context_injection_enabled': bool
        }
    """
    config = get_agent_config(project_id)
    return {
        "memory_enabled": config.get("memory_enabled", True),
        "observations_enabled": config.get("observations_enabled", True),
        "diary_enabled": config.get("diary_enabled", True),
        "patterns_enabled": config.get("patterns_enabled", True),
        "checkpoints_enabled": config.get("checkpoints_enabled", True),
        "context_injection_enabled": config.get("context_injection_enabled", True),
    }


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


# Valid RPM limit values (slider stops)
EXTRACTION_RPM_VALUES = (0, 5, 10, 15, 30, 60)
EXTRACTION_RPM_LABELS = {
    0: "Off",
    5: "Minimal",
    10: "Low",
    15: "Medium",
    30: "High",
    60: "Unlimited",
}


class ExtractionConfig(TypedDict):
    """Extraction throttle configuration."""

    enabled: bool
    rpm_limit: int
    rpm_label: str


def get_extraction_config(project_id: str) -> ExtractionConfig:
    """Get extraction throttle configuration for a project.

    Args:
        project_id: Project ID

    Returns:
        ExtractionConfig with enabled, rpm_limit, and rpm_label
    """
    config = get_agent_config(project_id)
    rpm_limit = config.get("extraction_rpm_limit", 10)
    return {
        "enabled": config.get("extraction_enabled", True),
        "rpm_limit": rpm_limit,
        "rpm_label": EXTRACTION_RPM_LABELS.get(rpm_limit, f"{rpm_limit} RPM"),
    }


def is_extraction_enabled(project_id: str) -> bool:
    """Check if extraction is enabled for a project.

    Returns False if extraction_enabled=False OR extraction_rpm_limit=0.

    Args:
        project_id: Project ID

    Returns:
        True if extraction is enabled and rpm_limit > 0
    """
    config = get_agent_config(project_id)
    if not config.get("extraction_enabled", True):
        return False
    return config.get("extraction_rpm_limit", 10) > 0


def get_extraction_rpm_limit(project_id: str) -> int:
    """Get the extraction RPM limit for a project.

    Args:
        project_id: Project ID

    Returns:
        RPM limit (0=disabled, 60=unlimited)
    """
    config = get_agent_config(project_id)
    if not config.get("extraction_enabled", True):
        return 0
    return config.get("extraction_rpm_limit", 10)
