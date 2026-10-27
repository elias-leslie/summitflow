"""Per-project database URL resolution by environment naming convention."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values

from ..logging_config import get_logger

logger = get_logger(__name__)

_ENV_LOCAL = Path.home() / ".env.local"


def _db_url_env_var(project_id: str) -> str:
    # 'summitflow' keeps the historical DATABASE_URL name; agent-hub -> AGENT_HUB_DB_URL.
    if project_id == "summitflow":
        return "DATABASE_URL"
    return f"{project_id.upper().replace('-', '_')}_DB_URL"


def get_db_url_for_project(project_id: str) -> str | None:
    """Return a project's database URL from the process environment, then ~/.env.local."""
    env_var = _db_url_env_var(project_id)
    url = os.environ.get(env_var)
    if not url and _ENV_LOCAL.is_file():
        url = dotenv_values(_ENV_LOCAL).get(env_var)
    if not url:
        logger.debug("No DB URL for %s (tried %s)", project_id, env_var)
    return url or None
