"""Validation helpers for mockups API."""

from pathlib import Path

from fastapi import HTTPException

from ..services.mockup_generator.storage_helpers import MOCKUP_BASE_DIR


def validate_mockup_path(file_path: str) -> Path:
    """Validate that a mockup file path is within the allowed base directory.

    Resolves symlinks and '..' components to prevent path traversal.

    Raises:
        HTTPException: If path is outside MOCKUP_BASE_DIR.
    """
    resolved = Path(file_path).resolve()
    base_resolved = MOCKUP_BASE_DIR.resolve()
    if not resolved.is_relative_to(base_resolved):
        raise HTTPException(
            status_code=403,
            detail="Access denied: path outside mockup storage",
        )
    return resolved
