"""Database configuration utilities for Explorer.

Handles database URL resolution and configuration for different projects.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

from ....logging_config import get_logger
from ....project_identity import list_project_identities

logger = get_logger(__name__)

# Load environment from ~/.env.local
_env_file = Path.home() / ".env.local"
if _env_file.exists():
    load_dotenv(_env_file)


@lru_cache(maxsize=1)
def _shared_database_layout() -> tuple[frozenset[str], dict[str, tuple[str, ...]]]:
    system_tables = {"alembic_version", "spatial_ref_sys"}
    guest_prefixes: dict[str, tuple[str, ...]] = {}

    for identity in list_project_identities():
        project = identity.get("project")
        database = identity.get("database")
        if not isinstance(project, dict) or not isinstance(database, dict):
            continue

        project_id = project.get("id")
        if not isinstance(project_id, str) or not project_id:
            continue

        version_table = database.get("version_table")
        if isinstance(version_table, str) and version_table:
            system_tables.add(version_table)

        legacy_version_tables = database.get("legacy_version_tables")
        if isinstance(legacy_version_tables, list):
            for table_name in legacy_version_tables:
                if isinstance(table_name, str) and table_name:
                    system_tables.add(table_name)

        table_prefixes: list[str] = []
        table_prefix = database.get("table_prefix")
        if isinstance(table_prefix, str) and table_prefix:
            table_prefixes.append(table_prefix)
        legacy_table_prefixes = database.get("legacy_table_prefixes")
        if isinstance(legacy_table_prefixes, list):
            table_prefixes.extend(
                prefix for prefix in legacy_table_prefixes if isinstance(prefix, str) and prefix
            )

        if database.get("shared_with") == "summitflow" and table_prefixes:
            guest_prefixes[project_id] = tuple(dict.fromkeys(table_prefixes))

    return frozenset(system_tables), guest_prefixes


SYSTEM_TABLES, _GUEST_TABLE_PREFIXES = _shared_database_layout()


def get_table_ownership_filter(project_id: str) -> tuple[str, ...] | None:
    """Return ownership info for projects sharing a database.

    Returns:
        For a guest project: a 1-tuple with its table prefix.
        For a host project sharing with guests: None (filtering handled by
            ``is_table_owned_by_project``).
        For projects with their own DB: None (no filtering needed).
    """
    return _GUEST_TABLE_PREFIXES.get(project_id)


def is_table_owned_by_project(project_id: str, table_name: str) -> bool:
    """Check whether *table_name* belongs to *project_id*.

    Rules:
    - Guest projects own only tables starting with their prefix.
    - Host projects that share a DB with guests own tables that do NOT
      start with any guest prefix.
    - Projects with their own dedicated DB own all tables.
    """
    guest_prefixes = _GUEST_TABLE_PREFIXES.get(project_id)
    if guest_prefixes:
        # Guest project: only own prefixed tables
        return any(table_name.startswith(prefix) for prefix in guest_prefixes)

    # Check if this project is a host sharing a DB with guests
    host_db_url = get_db_url_for_project(project_id)
    if host_db_url:
        for guest_id, prefixes in _GUEST_TABLE_PREFIXES.items():
            guest_db_url = get_db_url_for_project(guest_id)
            if (
                guest_db_url
                and _same_database(host_db_url, guest_db_url)
                and any(table_name.startswith(prefix) for prefix in prefixes)
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
