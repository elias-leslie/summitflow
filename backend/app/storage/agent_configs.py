"""Storage layer for agent configurations per project."""

from __future__ import annotations

from typing import TypedDict, cast

from psycopg.types.json import Jsonb

from ..constants import DEFAULT_CLAUDE_MODEL, DEFAULT_GEMINI_MODEL
from ..logging_config import get_logger
from .connection import get_connection, get_cursor

logger = get_logger(__name__)


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
    autonomous_frequency_minutes: int  # How often to check for work
    autonomous_max_concurrent: int  # Max concurrent autonomous tasks (1-3)
    autonomous_auto_merge_tiers: list[int]  # Tiers eligible for auto-merge
    autonomous_task_types: list[str]  # Labels eligible for autonomous execution
    upkeep_enabled: bool  # Enable routine upkeep signal discovery/routing
    upkeep_frequency_minutes: int  # How often routine upkeep may run
    upkeep_batch_limit: int  # Max tasks a routine upkeep cycle creates/dispatches
    work_pickup_enabled: bool  # Enable scheduled autonomous work pickup
    task_generation_enabled: bool  # Enable scheduled routine upkeep cron entrypoint
    reset_claims_enabled: bool  # Enable scheduled claim reset sweeps
    scan_projects_enabled: bool  # Enable scheduled project scans
    refresh_precision_indexes_enabled: bool  # Enable scheduled precision index refresh
    refresh_graphify_graphs_enabled: bool  # Enable scheduled Graphify code graph refresh
    scheduled_backups_enabled: bool  # Enable scheduled backup creation
    stale_cleanup_enabled: bool  # Enable scheduled stale cleanup jobs
    self_healing_enabled: bool  # Enable scheduled self-healing orchestrator
    prod_smoke_test_enabled: bool  # Enable scheduled production smoke tests
    health_monitor_enabled: bool  # Enable scheduled health monitor checks
    pending_drain_enabled: bool  # Enable scheduled backup drain
    restore_tests_enabled: bool  # Enable scheduled restore verification
    runtime_hygiene_enabled: bool  # Enable scheduled runtime hygiene audit
    autonomous_max_tasks_per_day: int | None  # Max tasks per day
    autonomous_cooldown_minutes: int  # Gap between autonomous dispatches
    autonomous_allowed_types: list[str] | None  # Allowed task types
    autonomous_max_self_fix_attempts: int  # Max self-fix attempts
    autonomous_max_supervisor_attempts: int  # Max supervisor attempts
    autonomous_max_extensions: int  # Max extension requests
    autonomous_auto_merge_enabled: bool  # Enable automatic merging
    autonomous_require_review: bool  # Require review before merge

    # Quality gate configuration
    quality_gate_tools: list[str]  # e.g. ["ruff", "types", "biome", "tsc"] - empty = st check --quick
    quality_gate_mode: str  # "quick", "check", or "changed-only"
    quality_gate_fix_enabled: bool  # Allow st check --fix during self-heal


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
    "autonomous_frequency_minutes": 30,
    "autonomous_max_concurrent": 1,  # Default: 1 concurrent task
    "autonomous_auto_merge_tiers": [1],
    "autonomous_task_types": ["auto-generated"],
    "upkeep_enabled": False,
    "upkeep_frequency_minutes": 120,
    "upkeep_batch_limit": 5,
    "work_pickup_enabled": True,
    "task_generation_enabled": True,
    "reset_claims_enabled": True,
    "scan_projects_enabled": True,
    "refresh_precision_indexes_enabled": True,
    "refresh_graphify_graphs_enabled": True,
    "scheduled_backups_enabled": True,
    "stale_cleanup_enabled": True,
    "self_healing_enabled": True,
    "prod_smoke_test_enabled": True,
    "health_monitor_enabled": True,
    "pending_drain_enabled": True,
    "restore_tests_enabled": True,
    "runtime_hygiene_enabled": False,
    "autonomous_max_tasks_per_day": None,
    "autonomous_cooldown_minutes": 0,
    "autonomous_allowed_types": None,
    "autonomous_max_self_fix_attempts": 3,
    "autonomous_max_supervisor_attempts": 3,
    "autonomous_max_extensions": 3,
    "autonomous_auto_merge_enabled": True,
    "autonomous_require_review": True,
    # Quality gate defaults
    "quality_gate_tools": [],  # Empty = use st check --quick (default behavior)
    "quality_gate_mode": "quick",
    "quality_gate_fix_enabled": True,
}


def get_agent_config(project_id: str) -> AgentConfig:
    """Get agent configuration for a project.

    Args:
        project_id: Project ID

    Returns:
        AgentConfig dict, or default config if not set
    """
    with get_cursor() as cur:
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
            logger.warning("Project %s not found, returning default config", project_id)
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


# Re-export submodule functions — consumed via `from ...storage import agent_configs`
# These imports are at the end to avoid circular dependencies
from .agent_configs_agents import (  # noqa: E402
    enable_agent,
    get_enabled_agents,
    set_default_agent,
)
from .agent_configs_autonomous import (  # noqa: E402
    get_allowed_task_types,
    get_auto_merge_enabled,
    get_cooldown_minutes,
    get_max_extensions,
    get_max_self_fix_attempts,
    get_max_supervisor_attempts,
    get_max_tasks_per_day,
    get_require_review,
)
from .agent_configs_components import (  # noqa: E402
    COMPONENT_SOURCES,
    get_component_source,
    set_component_source,
)
from .agent_configs_quality import (  # noqa: E402
    build_dt_command,
    build_st_check_command,
    get_quality_gate_fix_enabled,
    get_quality_gate_mode,
    get_quality_gate_tools,
)

__all__ = [
    "COMPONENT_SOURCES",
    "DEFAULT_AGENT_CONFIG",
    "AgentConfig",
    "build_dt_command",
    "build_st_check_command",
    "enable_agent",
    "get_agent_config",
    "get_allowed_task_types",
    "get_auto_merge_enabled",
    "get_component_source",
    "get_cooldown_minutes",
    "get_enabled_agents",
    "get_max_extensions",
    "get_max_self_fix_attempts",
    "get_max_supervisor_attempts",
    "get_max_tasks_per_day",
    "get_quality_gate_fix_enabled",
    "get_quality_gate_mode",
    "get_quality_gate_tools",
    "get_require_review",
    "set_component_source",
    "set_default_agent",
    "update_agent_config",
]
