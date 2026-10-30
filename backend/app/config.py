"""Centralized configuration loading.

Uses pydantic-settings for validated configuration with environment variable support.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Re-exported: the ports and URLs live in local_endpoints so st starts without Settings.
from .local_endpoints import (
    AGENT_HUB_URL as AGENT_HUB_URL,
)
from .local_endpoints import (
    DEFAULT_API_BASE as DEFAULT_API_BASE,
)
from .local_endpoints import (
    HATCHET_GRPC_PORT as HATCHET_GRPC_PORT,
)
from .local_endpoints import (
    HATCHET_HEALTH_PORT as HATCHET_HEALTH_PORT,
)
from .local_endpoints import (
    POSTGRES_PORT as POSTGRES_PORT,
)
from .local_endpoints import (
    REDIS_PORT as REDIS_PORT,
)
from .local_endpoints import (
    SUMMITFLOW_BACKEND_PORT as SUMMITFLOW_BACKEND_PORT,
)
from .local_endpoints import (
    SUMMITFLOW_FRONTEND_PORT as SUMMITFLOW_FRONTEND_PORT,
)
from .local_endpoints import (
    TETHER_DEFAULT_INSTANCE as TETHER_DEFAULT_INSTANCE,
)
from .local_endpoints import local_url
from .utils.maintenance_window import MaintenanceWindow


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
            local_url("monkey-fight", "frontend_port"),
            local_url("agent-hub", "frontend_port"),
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

    # The daily Google Drive copy (app/tasks/backup_offsite.py): restic retention for its snapshots, and how long the
    # per-source snapshots from before that job (no "offsite" tag) are kept while they age out.
    backup_offsite_keep_daily: int = 7
    backup_offsite_keep_weekly: int = 4
    backup_offsite_keep_monthly: int = 3
    backup_offsite_legacy_days: int = 30

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
