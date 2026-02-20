"""Centralized configuration loading.

Uses pydantic-settings for validated configuration with environment variable support.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        """Ensure database_url is provided."""
        if not v:
            raise ValueError("DATABASE_URL environment variable is required")
        return v

    # Redis
    redis_url: str = "redis://localhost:6379"

    # Hatchet
    hatchet_client_token: str = ""
    hatchet_client_tls_strategy: str = "none"

    # Web Push (VAPID)
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    vapid_subject: str = "mailto:admin@summitflow.dev"

    # CORS
    cors_origins: list[str] = [
        # Local development
        "http://localhost:3001",
        "http://localhost:4001",
        "http://localhost:3003",
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
