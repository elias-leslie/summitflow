"""Database configuration utilities for Explorer.

Handles database URL resolution and configuration for different projects.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

from ....logging_config import get_logger

logger = get_logger(__name__)

# Load environment from ~/.env.local
_env_file = Path.home() / ".env.local"
if _env_file.exists():
    load_dotenv(_env_file)

# System tables to exclude (includes prefixed variants like terminal_alembic_version)
SYSTEM_TABLES = {
    "alembic_version",
    "spatial_ref_sys",
    "terminal_alembic_version",
}

# Projects that share a database use table prefixes to separate ownership.
# The "host" project owns all unprefixed tables; "guest" projects own tables
# with their prefix (e.g. terminal_ tables belong to the terminal project).
# Format: project_id -> prefix (including trailing underscore).
_GUEST_TABLE_PREFIXES: dict[str, str] = {
    "terminal": "terminal_",
}


def get_table_ownership_filter(project_id: str) -> tuple[str, ...] | None:
    """Return ownership info for projects sharing a database.

    Returns:
        For a guest project: a 1-tuple with its table prefix.
        For a host project sharing with guests: None (filtering handled by
            ``is_table_owned_by_project``).
        For projects with their own DB: None (no filtering needed).
    """
    prefix = _GUEST_TABLE_PREFIXES.get(project_id)
    if prefix:
        return (prefix,)
    return None


def is_table_owned_by_project(project_id: str, table_name: str) -> bool:
    """Check whether *table_name* belongs to *project_id*.

    Rules:
    - Guest projects own only tables starting with their prefix.
    - Host projects that share a DB with guests own tables that do NOT
      start with any guest prefix.
    - Projects with their own dedicated DB own all tables.
    """
    guest_prefix = _GUEST_TABLE_PREFIXES.get(project_id)
    if guest_prefix:
        # Guest project: only own prefixed tables
        return table_name.startswith(guest_prefix)

    # Check if this project is a host sharing a DB with guests
    host_db_url = get_db_url_for_project(project_id)
    if host_db_url:
        for guest_id, prefix in _GUEST_TABLE_PREFIXES.items():
            guest_db_url = get_db_url_for_project(guest_id)
            if (
                guest_db_url
                and _same_database(host_db_url, guest_db_url)
                and table_name.startswith(prefix)
            ):
                return False

    return True


def _same_database(url_a: str, url_b: str) -> bool:
    """Check if two database URLs point to the same database (ignoring params)."""
    # Strip query params for comparison
    return url_a.split("?")[0] == url_b.split("?")[0]


def get_db_url_for_project(project_id: str) -> str | None:
    """Get database URL for a project using naming convention.

    Convention: PROJECT_ID.upper().replace('-','_') + '_DB_URL'
    Special case: 'summitflow' uses 'DATABASE_URL' for backwards compatibility.

    Args:
        project_id: The project identifier

    Returns:
        Database URL from environment or None if not set
    """
    # Special case for summitflow (existing convention)
    if project_id == "summitflow":
        return os.environ.get("DATABASE_URL")

    # Convention: agent-hub -> AGENT_HUB_DB_URL
    env_var = f"{project_id.upper().replace('-', '_')}_DB_URL"
    url = os.environ.get(env_var)

    if not url:
        logger.debug("No DB URL for %s (tried %s)", project_id, env_var)

    return url
