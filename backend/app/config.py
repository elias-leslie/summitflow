"""Centralized configuration loading.

Uses pydantic-settings for validated configuration with environment variable support.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# Project ports live in each project's project.identity.json (runtime
# backend_port/frontend_port). SummitFlow reads its own from its identity; the
# infra ports below belong to SummitFlow's own stack.
def _own_runtime_port(key: str) -> int:
    import json

    from .utils.shared_paths import get_repo_root

    identity = json.loads((get_repo_root() / "project.identity.json").read_text(encoding="utf-8"))
    return int(identity["runtime"][key])


SUMMITFLOW_BACKEND_PORT = _own_runtime_port("backend_port")
SUMMITFLOW_FRONTEND_PORT = _own_runtime_port("frontend_port")


def _local_url(project_id: str, key: str) -> str:
    """http://localhost:<port> from another project's identity, or "" when it is not on this host."""
    from .project_identity import get_runtime_port

    port = get_runtime_port(project_id, key)
    return f"http://localhost:{port}" if port else ""

POSTGRES_PORT = 5432
REDIS_PORT = 6379
HATCHET_GRPC_PORT = 7070
HATCHET_HEALTH_PORT = 8888
# Tether (per-user session daemon for Aico and A-Term) has no TCP port: it serves
# its API on $XDG_RUNTIME_DIR/tether/<instance>/control.sock under
# tether@<instance>.service. TETHER_SOCKET overrides the socket path.
TETHER_DEFAULT_INSTANCE = "default"


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
        origin for origin in (
            f"http://localhost:{SUMMITFLOW_FRONTEND_PORT}",
            _local_url("monkey-fight", "frontend_port"),
            _local_url("agent-hub", "frontend_port"),
        ) if origin
    ]

    # Cloudflare Access / SummitFlow identity.
    cloudflare_access_team_domain: str = ""
    cloudflare_access_aud: str = ""
    summitflow_owner_emails: str = ""

    backup_btrbk_enabled: bool = False

    # Optional local-time window for the existing scheduled backup workflow.
    # Unset hours preserve unrestricted scheduling; manual backups are separate.
    backup_schedule_start_hour: int | None = Field(default=None, ge=0, le=23)
    backup_schedule_end_hour: int | None = Field(default=None, ge=0, le=23)
    backup_schedule_timezone: str = "America/New_York"

    @field_validator("backup_schedule_timezone")
    @classmethod
    def validate_backup_schedule_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ValueError, ZoneInfoNotFoundError) as exc:
            raise ValueError("Backup schedule timezone must be an IANA timezone") from exc
        return value

    @model_validator(mode="after")
    def validate_backup_schedule_window(self) -> Settings:
        start, end = self.backup_schedule_start_hour, self.backup_schedule_end_hour
        if (start is None) != (end is None):
            raise ValueError("Backup schedule requires both start and end hours")
        if start is not None and start == end:
            raise ValueError("Backup schedule start and end hours must differ")
        return self


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
AGENT_HUB_URL = _env_or_default("AGENT_HUB_URL", _local_url("agent-hub", "backend_port"))
