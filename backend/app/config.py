"""Centralized configuration loading.

Uses pydantic-settings for validated configuration with environment variable support.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# ---------------------------------------------------------------------------
# Port allocation — single source of truth for the SummitFlow management plane.
# Other projects define their own ports in their own config.py; these are here
# because SummitFlow manages the full runtime (docker/constants.py, smoke_test, etc.).
# ---------------------------------------------------------------------------
SUMMITFLOW_BACKEND_PORT = 8001
SUMMITFLOW_FRONTEND_PORT = 3001
AGENT_HUB_BACKEND_PORT = 8003
AGENT_HUB_FRONTEND_PORT = 3003
A_TERM_BACKEND_PORT = 8002
A_TERM_FRONTEND_PORT = 3002
PORTFOLIO_BACKEND_PORT = 8000
PORTFOLIO_FRONTEND_PORT = 3000
SHA_BACKEND_PORT = 8010
SHA_FRONTEND_PORT = 3010
MONKEY_FIGHT_PORT = 4001
VANTAGE_BACKEND_PORT = 8004
VANTAGE_FRONTEND_PORT = 3004
TEST1_BACKEND_PORT = 9001
TEST1_FRONTEND_PORT = 4004
TEST2_BACKEND_PORT = 9002
TEST2_FRONTEND_PORT = 4002
TEST3_BACKEND_PORT = 9003
TEST3_FRONTEND_PORT = 4003
HERMES_DASHBOARD_PORT = 9119
POSTGRES_PORT = 5432
REDIS_PORT = 6379
HATCHET_GRPC_PORT = 7070
HATCHET_HEALTH_PORT = 8888


def _env_or_default(name: str, default: str) -> str:
    """Return stripped env value or default when unset/blank."""
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    return value or default


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    Loads from ~/.env.local by default.
    """

    model_config = SettingsConfigDict(
        env_file=str(Path.home() / ".env.local"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    database_url: str = ""
    database_admin_url: str = ""

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        """Ensure database_url is provided."""
        if not v:
            raise ValueError("DATABASE_URL environment variable is required")
        return v

    # Redis
    redis_url: str = f"redis://localhost:{REDIS_PORT}"

    # Hatchet
    hatchet_client_token: str = ""

    # CORS
    cors_origins: list[str] = [
        f"http://localhost:{SUMMITFLOW_FRONTEND_PORT}",
        f"http://localhost:{MONKEY_FIGHT_PORT}",
        f"http://localhost:{AGENT_HUB_FRONTEND_PORT}",
    ]


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance.

    Returns:
        Settings instance (cached for performance)
    """
    return Settings()


# Pre-loaded for modules that need them at import time
# These provide backward compatibility with existing code
settings = get_settings()
DATABASE_URL = settings.database_url
REDIS_URL = settings.redis_url
DEFAULT_API_BASE = _env_or_default("ST_API_BASE", f"http://localhost:{SUMMITFLOW_BACKEND_PORT}/api")
AGENT_HUB_URL = _env_or_default("AGENT_HUB_URL", f"http://localhost:{AGENT_HUB_BACKEND_PORT}")
