"""Storage layer for agent configurations per project."""

from __future__ import annotations

from typing import Any, TypedDict, cast

from psycopg.types.json import Jsonb

from ..logging_config import get_logger
from .connection import get_connection, get_cursor

logger = get_logger(__name__)


class AgentConfig(TypedDict, total=False):
    """Per-project schedule kill switches and publication settings."""

    reset_claims_enabled: bool  # Enable scheduled claim reset sweeps
    refresh_project_indexes_enabled: bool  # Enable scheduled .index.yaml refresh
    refresh_graphify_graphs_enabled: bool  # Enable scheduled Graphify code graph refresh
    scheduled_backups_enabled: bool  # Enable scheduled backup creation
    stale_cleanup_enabled: bool  # Enable scheduled stale cleanup jobs
    prod_smoke_test_enabled: bool  # Enable scheduled production smoke tests
    health_monitor_enabled: bool  # Enable scheduled health monitor checks
    runtime_hygiene_enabled: bool  # Enable scheduled runtime hygiene audit
    nightly_publication_enabled: bool  # Enable the overnight publication sweep (system kill switch)
    nightly_deep_lane_enabled: bool  # Enable the nightly deep lane (system kill switch)
    nightly_security_alert_enabled: bool  # Enable the nightly OSV security alert (system kill switch)
    publication_mode: str  # Per project: "nightly" (hourly push) or "manual" (default)
    publication_hold: dict[str, Any] | None  # {"through": OID | None, "reason", "set_at"}; keeps later commits local


DEFAULT_AGENT_CONFIG: AgentConfig = {
    "reset_claims_enabled": True,
    "refresh_project_indexes_enabled": True,
    "refresh_graphify_graphs_enabled": True,
    "scheduled_backups_enabled": True,
    "stale_cleanup_enabled": True,
    "prod_smoke_test_enabled": True,
    "health_monitor_enabled": True,
    "runtime_hygiene_enabled": False,
    "nightly_publication_enabled": True,
    "nightly_deep_lane_enabled": True,
    "nightly_security_alert_enabled": True,
    "publication_mode": "manual",
}


def _get_stored_agent_config(project_id: str) -> AgentConfig:
    """Read the persisted SummitFlow config without execution context overlays."""
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

    if row is None or row[0] is None:
        if row is None:
            logger.warning("Project %s not found, returning default config", project_id)
        return DEFAULT_AGENT_CONFIG.copy()

    result = DEFAULT_AGENT_CONFIG.copy()
    result.update(row[0])
    return result


def get_agent_config(project_id: str) -> AgentConfig:
    """Get the stored agent config for a project, merged over defaults.

    Args:
        project_id: Project ID

    Returns:
        AgentConfig dict, or default config if not set
    """
    return _get_stored_agent_config(project_id)


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
    current = _get_stored_agent_config(project_id)

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


__all__ = [
    "DEFAULT_AGENT_CONFIG",
    "AgentConfig",
    "get_agent_config",
    "update_agent_config",
]
