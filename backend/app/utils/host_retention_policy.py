"""Host retention policy configuration."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import Any

# Owner settings (Runtime > Maintenance > Cleanup ages) override env and defaults. A plain file, so the emergency
# reclaim still reads them when Postgres is down or the disk is full.
SETTINGS_PATH = Path(os.environ.get("SF_HOST_RETENTION_SETTINGS") or Path.home() / ".config" / "summitflow" / "host-retention.json")
# Fields the settings UI edits, with their allowed range (unit is in the field name).
EDITABLE: dict[str, tuple[float, float]] = {
    "agent_tmp_max_age_hours": (6, 24 * 30),
    "build_tmp_max_age_hours": (6, 24 * 30),
    "go_cache_max_gb": (1, 200),
}


def read_settings(path: Path | None = None) -> dict[str, Any]:
    """Saved owner overrides; empty when the file is missing or unreadable."""
    try:
        data = json.loads((path or SETTINGS_PATH).read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def validate_settings(values: dict[str, Any]) -> dict[str, float]:
    """Only editable fields, numeric and inside their range; raises ValueError with a plain reason."""
    clean: dict[str, float] = {}
    for name, value in values.items():
        if name not in EDITABLE:
            raise ValueError(f"{name} can't be changed here")
        low, high = EDITABLE[name]
        if isinstance(value, bool) or not isinstance(value, int | float) or not low <= value <= high:
            raise ValueError(f"{name} must be a number from {low:g} to {high:g}")
        clean[name] = value
    return clean


def write_settings(values: dict[str, Any], path: Path | None = None) -> dict[str, float]:
    """Save overrides; a None value clears that setting back to its default."""
    target = path or SETTINGS_PATH
    cleared = {name for name, value in values.items() if value is None and name in EDITABLE}
    kept = {k: v for k, v in read_settings(target).items() if k in EDITABLE and k not in cleared}
    merged = {**kept, **validate_settings({k: v for k, v in values.items() if v is not None})}
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(merged, indent=2, sort_keys=True) + "\n")
    tmp.replace(target)
    return merged


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
    npx_max_age_hours: int = 7 * 24
    playwright_max_age_hours: int = 14 * 24
    tmp_backup_max_age_hours: int = 2 * 24
    hermes_checkpoint_tmp_max_age_hours: int = 2 * 24
    hermes_checkpoint_internal_max_age_hours: int = 3 * 24
    legacy_report_max_age_hours: int = 3 * 24
    scratch_review_max_age_hours: int = 7 * 24
    # Scratch age when its filesystem is under pressure. It matches the weekly
    # age: pressure runs retention now, it does not shorten the window, so idle
    # owner work (e.g. a large experiment) is not deleted after two quiet days.
    scratch_pressure_max_age_hours: int = 7 * 24
    # Per-project `st check` evidence (see app.tasks._retention_check_artifacts).
    check_details_max_age_hours: int = 7 * 24
    check_stages_max_age_hours: int = 14 * 24
    check_observations_max_age_hours: int = 3 * 24
    # One failed run is enough to diagnose; each run is ~700MB.
    check_observations_keep: int = 3
    # Agent temp in /tmp: an agent session dir (/tmp/claude-*/<project>/<session>) or a top-level build temp entry
    # goes once nothing in it changed for this long and no process holds it.
    agent_tmp_max_age_hours: int = 3 * 24
    build_tmp_max_age_hours: int = 2 * 24
    # Go's build cache is cleared daily once it is larger than this; an emergency reclaim always clears it.
    go_cache_max_gb: float = 4.0
    # Regenerable tool caches cleared daily once over their cap (uv and npm only drop unused entries by themselves, so
    # a busy host's cache just grows). pnpm's store and unused Hugging Face repos are pruned daily without a cap.
    uv_cache_max_gb: float = 8.0
    npm_cache_max_gb: float = 2.0
    # Each service release cache (<state root>/cache/uv, cache/pnpm-store) is emptied once over this; every package
    # is re-downloadable and releases hold clones, not links. pnpm's own prune cannot be used on a clone-imported store.
    release_cache_max_gb: float = 8.0

    @classmethod
    def from_env(cls) -> HostRetentionPolicy:
        """Defaults, then SF_HOST_RETENTION_* env, then the owner's saved settings for the editable fields."""
        policy = cls._env_only()
        saved = read_settings()
        types = {f.name: f.type for f in fields(cls)}
        overrides: dict[str, Any] = {}
        for name, value in saved.items():
            if name in EDITABLE:
                try:
                    validate_settings({name: value})
                except ValueError:
                    continue
                overrides[name] = int(value) if types.get(name) in (int, "int") else float(value)
        return replace(policy, **overrides) if overrides else policy

    @classmethod
    def _env_only(cls) -> HostRetentionPolicy:
        return cls(
            pressure_disk_percent=_float_env("SF_HOST_RETENTION_PRESSURE_DISK_PERCENT", 75.0),
            pressure_min_free_gb=_float_env("SF_HOST_RETENTION_PRESSURE_MIN_FREE_GB", 25.0),
            npx_max_age_hours=_int_env("SF_HOST_RETENTION_NPX_MAX_AGE_HOURS", 7 * 24),
            playwright_max_age_hours=_int_env(
                "SF_HOST_RETENTION_PLAYWRIGHT_MAX_AGE_HOURS", 14 * 24
            ),
            tmp_backup_max_age_hours=_int_env(
                "SF_HOST_RETENTION_TMP_BACKUP_MAX_AGE_HOURS", 2 * 24
            ),
            hermes_checkpoint_tmp_max_age_hours=_int_env(
                "SF_HOST_RETENTION_HERMES_CHECKPOINT_TMP_MAX_AGE_HOURS", 2 * 24
            ),
            hermes_checkpoint_internal_max_age_hours=_int_env(
                "SF_HOST_RETENTION_HERMES_CHECKPOINT_INTERNAL_MAX_AGE_HOURS", 3 * 24
            ),
            legacy_report_max_age_hours=_int_env(
                "SF_HOST_RETENTION_LEGACY_REPORT_MAX_AGE_HOURS", 3 * 24
            ),
            scratch_review_max_age_hours=_int_env(
                "SF_HOST_RETENTION_SCRATCH_REVIEW_MAX_AGE_HOURS", 7 * 24
            ),
            scratch_pressure_max_age_hours=_int_env(
                "SF_HOST_RETENTION_SCRATCH_PRESSURE_MAX_AGE_HOURS", 7 * 24
            ),
            agent_tmp_max_age_hours=_int_env("SF_HOST_RETENTION_AGENT_TMP_MAX_AGE_HOURS", 3 * 24),
            build_tmp_max_age_hours=_int_env("SF_HOST_RETENTION_BUILD_TMP_MAX_AGE_HOURS", 2 * 24),
            go_cache_max_gb=_float_env("SF_HOST_RETENTION_GO_CACHE_MAX_GB", 4.0),
            uv_cache_max_gb=_float_env("SF_HOST_RETENTION_UV_CACHE_MAX_GB", 8.0),
            npm_cache_max_gb=_float_env("SF_HOST_RETENTION_NPM_CACHE_MAX_GB", 2.0),
            release_cache_max_gb=_float_env("SF_HOST_RETENTION_RELEASE_CACHE_MAX_GB", 8.0),
        )

    def defaults_for(self) -> dict[str, float]:
        """Env/default values of the editable fields (what a cleared setting falls back to)."""
        base = type(self)._env_only()
        return {name: getattr(base, name) for name in EDITABLE}
