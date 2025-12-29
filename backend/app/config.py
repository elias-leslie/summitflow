"""Centralized configuration loading.

Loads environment from ~/.env.local and provides access to common settings.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load environment from ~/.env.local (same pattern as ~/.smbcredentials)
_env_file = Path.home() / ".env.local"
if _env_file.exists():
    load_dotenv(_env_file)


def get_database_url() -> str:
    """Get DATABASE_URL from environment.

    Returns:
        Database URL string

    Raises:
        RuntimeError: If DATABASE_URL is not set
    """
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL environment variable is required. "
            "Create ~/.env.local with DATABASE_URL=postgresql://..."
        )
    return url


def get_redis_url() -> str:
    """Get REDIS_URL from environment.

    Returns:
        Redis URL string (defaults to localhost if not set)
    """
    return os.getenv("REDIS_URL", "redis://localhost:6379")


# Pre-loaded for modules that need them at import time
DATABASE_URL = get_database_url()
REDIS_URL = get_redis_url()
