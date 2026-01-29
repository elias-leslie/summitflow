"""Storage helpers for mockup generation."""

from __future__ import annotations

import uuid
from pathlib import Path

# Directory for storing mockup images
MOCKUP_BASE_DIR = Path("/tmp/summitflow/mockups")


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
