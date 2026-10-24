"""Centralized configuration loading.

Uses pydantic-settings for validated configuration with environment variable support.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .utils.maintenance_window import MaintenanceWindow


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

    try:
        port = get_runtime_port(project_id, key)
    except (OSError, ValueError):  # another project's unreadable identity must not break SummitFlow
        return ""
    return f"http://localhost:{port}" if port else ""

POSTGRES_PORT = 5432
REDIS_PORT = 6379
HATCHET_GRPC_PORT = 7070
HATCHET_HEALTH_PORT = 8888
# Tether (Aico's per-user session daemon) has no TCP port: it serves
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

    # Owner by credential, not address. While summitflow_loopback_is_owner is on (default,
    # SUMMITFLOW_LOOPBACK_IS_OWNER) every local caller is the owner. Off, a caller is the owner only with
    # the token in summitflow_owner_token_file (X-SummitFlow-Owner-Token) or a Cloudflare Access identity;
    # the token in summitflow_agent_token_file (X-SummitFlow-Agent-Token) gets the agent role: the API
    # except the owner-only decisions. Anyone else is unauthenticated.
    summitflow_loopback_is_owner: bool = True
    summitflow_owner_token_file: str = ""
    summitflow_agent_token_file: str = ""

    backup_btrbk_enabled: bool = False

    # A disabled backup source with no repository capture for this many days has its restic points forgotten and
    # pruned by scheduled maintenance (only when that maintenance is prune-qualified and healthy). 0 turns it off.
    backup_retire_disabled_after_days: int = 30

    # Optional window for the existing scheduled backup workflow, in the shared maintenance-window format
    # (app/utils/maintenance_window.py): "02:00-06:00", up to 4 comma-joined ranges, a trailing Z for UTC. Otherwise it
    # reads in backup_schedule_timezone. Unset preserves unrestricted scheduling; manual backups are separate.
    backup_schedule_window: str | None = None
    backup_schedule_timezone: str = "America/New_York"

    @field_validator("backup_schedule_timezone")
    @classmethod
    def validate_backup_schedule_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ValueError, ZoneInfoNotFoundError) as exc:
            raise ValueError("Backup schedule timezone must be an IANA timezone") from exc
        return value

    @field_validator("backup_schedule_window", mode="before")
    @classmethod
    def validate_backup_schedule_window(cls, value: str | None) -> str | None:
        if value is None or not str(value).strip():
            return None
        MaintenanceWindow.parse(str(value).strip())
        return str(value).strip()


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
