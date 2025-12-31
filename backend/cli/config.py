"""CLI configuration management."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class Config:
    """CLI configuration loaded from environment variables."""

    api_base: str
    project_id: str


@lru_cache
def get_config() -> Config:
    """Get CLI configuration from environment variables.

    Returns:
        Config with api_base and project_id.
    """
    return Config(
        api_base=os.getenv("ST_API_BASE", "http://localhost:8001/api"),
        project_id=os.getenv("ST_PROJECT_ID", "summitflow"),
    )
