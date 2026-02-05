"""Centralized configuration loading.

Uses pydantic-settings for validated configuration with environment variable support.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
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

    database_url: str = Field(
        ...,
        description="PostgreSQL connection URL",
        json_schema_extra={"env": "DATABASE_URL"},
    )
    redis_url: str = Field(
        default="redis://localhost:6379",
        description="Redis connection URL",
        json_schema_extra={"env": "REDIS_URL"},
    )
    cors_origins: list[str] = Field(
        default=[
            "http://localhost:3001",
            "http://192.168.8.233:3001",
            "https://dev.summitflow.dev",
            "http://localhost:4001",
            "https://test1.summitflow.dev",
            # Agent Hub cross-origin requests
            "http://localhost:3003",
            "https://agent.summitflow.dev",
        ],
        description="Allowed CORS origins for cross-origin requests",
        json_schema_extra={"env": "CORS_ORIGINS"},
    )


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
