"""Shared path helpers for the SummitFlow repo."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]


def get_repo_root() -> Path:
    """Return the canonical SummitFlow repo root for the current process."""
    override = os.environ.get("SUMMITFLOW_ROOT", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return _REPO_ROOT


def get_scripts_dir() -> Path:
    """Return the shared SummitFlow scripts directory."""
    return get_repo_root() / "scripts"


def resolve_script(script_name: str) -> Path:
    """Return the best-available path for a shared SummitFlow script."""
    direct = get_scripts_dir() / script_name
    if direct.exists():
        return direct

    from_path = shutil.which(script_name)
    if from_path:
        return Path(from_path).resolve()

    return direct
