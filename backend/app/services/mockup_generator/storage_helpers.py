"""Storage helpers for Design Ops mockup and asset generation."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
_DEFAULT_MOCKUP_BASE_DIR = _REPO_ROOT / "data" / "design-studio" / "mockups"
_TMP_ROOT = Path("/tmp").resolve()


def _resolve_mockup_base_dir() -> Path:
    """Resolve durable Design Ops storage and refuse temporary locations."""
    configured = os.environ.get("SUMMITFLOW_MOCKUP_BASE_DIR")
    base_dir = Path(configured).expanduser() if configured else _DEFAULT_MOCKUP_BASE_DIR
    if configured and not base_dir.is_absolute():
        base_dir = _REPO_ROOT / base_dir
    resolved = base_dir.resolve(strict=False)
    if resolved == _TMP_ROOT or _TMP_ROOT in resolved.parents:
        raise RuntimeError(
            "Refusing to use /tmp for Design Ops mockup/asset storage. "
            "Set SUMMITFLOW_MOCKUP_BASE_DIR to a durable path."
        )
    return resolved


# Durable storage for UI mockups and Asset Studio images. Do not use /tmp:
# generated/imported design artifacts must survive service and host restarts.
MOCKUP_BASE_DIR = _resolve_mockup_base_dir()


def generate_mockup_id() -> str:
    """Generate a new mockup ID in the format mk-{uuid}."""
    return f"mk-{uuid.uuid4().hex[:12]}"


def get_mockup_directory(project_id: str, mockup_id: str) -> Path:
    """Get the directory path for a mockup.

    Args:
        project_id: Project ID
        mockup_id: Mockup ID

    Returns:
        Path to the mockup directory
    """
    return MOCKUP_BASE_DIR / project_id / mockup_id


__all__ = ["MOCKUP_BASE_DIR", "generate_mockup_id", "get_mockup_directory"]
