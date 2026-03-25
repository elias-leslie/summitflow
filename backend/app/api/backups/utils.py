"""Utility functions for backup API."""

from typing import cast

from fastapi import HTTPException

from ...storage import backups as backup_store
from ...utils.datetime_helpers import parse_iso_datetime

__all__ = [
    "as_object_dict",
    "optional_bool",
    "optional_str",
    "parse_iso_datetime",
    "validate_backup_access",
]


def optional_str(value: object) -> str | None:
    """Return a string value or None for non-string inputs."""
    return value if isinstance(value, str) and value.strip() else None


def optional_bool(value: object) -> bool | None:
    """Return a boolean value or None for non-boolean inputs."""
    return value if isinstance(value, bool) else None


def as_object_dict(value: object) -> dict[str, object]:
    """Return a dict[str, object] when possible, otherwise an empty dict."""
    return cast(dict[str, object], value) if isinstance(value, dict) else {}


def validate_backup_access(project_id: str, backup_id: str) -> dict[str, object]:
    """Validate backup exists and belongs to project.

    Args:
        project_id: Project ID to validate against
        backup_id: Backup ID to retrieve

    Returns:
        Backup data if found and accessible

    Raises:
        HTTPException: If backup not found or access denied
    """
    backup = backup_store.get_backup(backup_id)
    if not backup:
        raise HTTPException(status_code=404, detail=f"Backup {backup_id} not found")
    if backup["project_id"] != project_id:
        raise HTTPException(
            status_code=404,
            detail=f"Backup {backup_id} not found in project {project_id}",
        )
    return backup
