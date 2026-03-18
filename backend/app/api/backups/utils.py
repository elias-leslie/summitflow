"""Utility functions for backup API."""

from fastapi import HTTPException

from ...storage import backups as backup_store
from ...utils.datetime_helpers import parse_iso_datetime

__all__ = ["parse_iso_datetime", "validate_backup_access"]


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
