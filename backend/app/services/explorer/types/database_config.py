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

# System tables to exclude
SYSTEM_TABLES = {
    "celery_taskmeta",
    "celery_tasksetmeta",
    "alembic_version",
    "spatial_ref_sys",
}


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
        logger.debug(f"No DB URL for {project_id} (tried {env_var})")

    return url
