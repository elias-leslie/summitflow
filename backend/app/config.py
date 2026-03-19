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
TERMINAL_BACKEND_PORT = 8002
TERMINAL_FRONTEND_PORT = 3002
PORTFOLIO_BACKEND_PORT = 8000
PORTFOLIO_FRONTEND_PORT = 3000
MONKEY_FIGHT_PORT = 4001
POSTGRES_PORT = 5432
REDIS_PORT = 6379
HATCHET_GRPC_PORT = 7070
HATCHET_HEALTH_PORT = 8888


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
        # Local development
        f"http://localhost:{SUMMITFLOW_FRONTEND_PORT}",
        f"http://localhost:{MONKEY_FIGHT_PORT}",
        f"http://localhost:{AGENT_HUB_FRONTEND_PORT}",
        # Production
        "https://dev.summitflow.dev",
        "https://test1.summitflow.dev",
        "https://agent.summitflow.dev",
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
DEFAULT_API_BASE = os.getenv("ST_API_BASE", f"http://localhost:{SUMMITFLOW_BACKEND_PORT}/api")
AGENT_HUB_URL = os.getenv("AGENT_HUB_URL", f"http://localhost:{AGENT_HUB_BACKEND_PORT}")
