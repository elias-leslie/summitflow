"""Centralized configuration loading.

Uses pydantic-settings for validated configuration with environment variable support.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
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
        default="",  # Validated to be non-empty; loaded from DATABASE_URL env var
        description="PostgreSQL connection URL",
        json_schema_extra={"env": "DATABASE_URL"},
    )

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        """Ensure database_url is provided."""
        if not v:
            raise ValueError("DATABASE_URL environment variable is required")
        return v

    redis_url: str = Field(
        default="redis://localhost:6379",
        description="Redis connection URL",
        json_schema_extra={"env": "REDIS_URL"},
    )
    hatchet_client_token: str = Field(
        default="",
        description="Hatchet client token for workflow orchestration",
        json_schema_extra={"env": "HATCHET_CLIENT_TOKEN"},
    )
    hatchet_client_tls_strategy: str = Field(
        default="none",
        description="Hatchet TLS strategy (none for local)",
        json_schema_extra={"env": "HATCHET_CLIENT_TLS_STRATEGY"},
    )
    cors_origins: list[str] = Field(
        default=[
            # Local development
            "http://localhost:3001",
            "http://localhost:4001",
            "http://localhost:3003",
            # Production
            "https://dev.summitflow.dev",
            "https://test1.summitflow.dev",
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
