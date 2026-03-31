"""Host retention policy configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(frozen=True, slots=True)
class HostRetentionPolicy:
    """Safe retention policy for rebuildable host artifacts."""

    pressure_disk_percent: float = 75.0
    pressure_min_free_gb: float = 25.0
    builder_cache_target_gb: int = 2
    builder_cache_pressure_target_gb: int = 1
    image_max_age_hours: int = 0
    image_pressure_max_age_hours: int = 0
    anonymous_volume_max_age_hours: int = 2 * 24
    npx_max_age_hours: int = 7 * 24
    playwright_max_age_hours: int = 14 * 24
    legacy_report_max_age_hours: int = 3 * 24

    @classmethod
    def from_env(cls) -> HostRetentionPolicy:
        return cls(
            pressure_disk_percent=_float_env("SF_HOST_RETENTION_PRESSURE_DISK_PERCENT", 75.0),
            pressure_min_free_gb=_float_env("SF_HOST_RETENTION_PRESSURE_MIN_FREE_GB", 25.0),
            builder_cache_target_gb=_int_env("SF_HOST_RETENTION_BUILDER_CACHE_TARGET_GB", 2),
            builder_cache_pressure_target_gb=_int_env(
                "SF_HOST_RETENTION_BUILDER_CACHE_PRESSURE_TARGET_GB", 1
            ),
            image_max_age_hours=_int_env("SF_HOST_RETENTION_IMAGE_MAX_AGE_HOURS", 0),
            image_pressure_max_age_hours=_int_env(
                "SF_HOST_RETENTION_IMAGE_PRESSURE_MAX_AGE_HOURS", 0
            ),
            anonymous_volume_max_age_hours=_int_env(
                "SF_HOST_RETENTION_ANON_VOLUME_MAX_AGE_HOURS", 2 * 24
            ),
            npx_max_age_hours=_int_env("SF_HOST_RETENTION_NPX_MAX_AGE_HOURS", 7 * 24),
            playwright_max_age_hours=_int_env(
                "SF_HOST_RETENTION_PLAYWRIGHT_MAX_AGE_HOURS", 14 * 24
            ),
            legacy_report_max_age_hours=_int_env(
                "SF_HOST_RETENTION_LEGACY_REPORT_MAX_AGE_HOURS", 3 * 24
            ),
        )
