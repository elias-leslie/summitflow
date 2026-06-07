"""Shared path helpers for the SummitFlow repo."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_WORKSPACES_ROOT = Path.home() / ".local" / "share" / "summitflow" / "workspaces"


def get_repo_root() -> Path:
    """Return the canonical SummitFlow repo root for the current process."""
    override = os.environ.get("SUMMITFLOW_ROOT", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return _REPO_ROOT


def get_scripts_dir() -> Path:
    """Return the shared SummitFlow scripts directory."""
    return get_repo_root() / "scripts"


def get_workspaces_root() -> Path:
    """Return the canonical shared Btrfs workspaces root."""
    raw = os.environ.get("ST_WORKSPACES_ROOT", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return _DEFAULT_WORKSPACES_ROOT


def get_shared_cache_dir(cache_name: str | None = None) -> Path:
    """Return the shared cache root or a named cache directory."""
    cache_root = get_workspaces_root() / "cache"
    if cache_name:
        cache_root = cache_root / cache_name
    return cache_root


def resolve_script(script_name: str) -> Path:
    """Return the best-available path for a shared SummitFlow script."""
    direct = get_scripts_dir() / script_name
    if direct.exists():
        return direct

    from_path = shutil.which(script_name)
    if from_path:
        return Path(from_path).resolve()

    return direct
