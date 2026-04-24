"""Backup restoration logic."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..logging_config import get_logger
from ..storage import backups as backup_store
from .backup_native import locate_archive, restore_archive
from .backup_utils import get_project_root, get_source_path

logger = get_logger(__name__)


def restore_backup(
    project_id: str,
    backup_id: str | None = None,
    backup_file: str | None = None,
    dry_run: bool = False,
    db_only: bool = False,
    files_only: bool = False,
    source_id: str | None = None,
) -> dict[str, Any]:
    """Restore from a backup through the native backup engine.

    Args:
        project_id: Project ID (fallback for path resolution)
        backup_id: Backup record ID
        backup_file: Direct path to backup archive (alternative to backup_id)
        dry_run: Show what would be restored without doing it
        db_only: Restore database only
        files_only: Restore files only
        source_id: Backup source ID (preferred for path resolution)

    Returns:
        Restore result dict
    """
    resolved_id = source_id or project_id

    logger.info(
        "restore_backup_started",
        source_id=resolved_id,
        backup_id=backup_id,
        dry_run=dry_run,
    )

    restore_dir = get_source_path(source_id) if source_id else None
    if not restore_dir:
        restore_dir = get_project_root(project_id)
    if not restore_dir:
        error_msg = f"Source {resolved_id} not found or has no path"
        logger.error("restore_backup_failed", error=error_msg)
        return {"status": "failed", "error": error_msg}

    try:
        backup_record = backup_store.get_backup(backup_id) if backup_id else None
        archive = locate_archive(Path(restore_dir), backup_record, backup_file)
        if archive is None:
            archive_name = _resolve_archive_name(backup_record)
            return _handle_restore_failure(resolved_id, f"Archive not found locally or pending: {archive_name or backup_file}")
        result = restore_archive(
            archive,
            Path(restore_dir),
            dry_run=dry_run,
            db_only=db_only,
            files_only=files_only,
        )
        return _handle_restore_success(resolved_id, dry_run, result)
    except Exception as e:
        logger.error("restore_backup_exception", source_id=resolved_id)
        return {"status": "failed", "error": str(e)}


def _backup_has_database(backup: dict[str, Any]) -> bool:
    """Check whether a backup record contains a real database dump."""
    vj = backup.get("verification_json") or {}
    if isinstance(vj.get("has_db"), bool):
        return vj["has_db"]
    return (backup.get("db_size_bytes") or 0) > 0


def _resolve_archive_name(backup: dict[str, Any] | None) -> str | None:
    """Resolve the archive filename for a backup record."""
    if not backup:
        return None

    location = str(backup.get("location") or "")
    if location and location != "pending_upload":
        return Path(location).name

    name = str(backup.get("name") or "")
    if name.endswith(".tar.gz"):
        return name

    return None


def _handle_restore_success(source_id: str, dry_run: bool, result: dict[str, Any]) -> dict[str, Any]:
    """Handle successful restore."""
    logger.info("restore_backup_completed", source_id=source_id, dry_run=dry_run)
    return {
        "status": "completed",
        "source_id": source_id,
        "dry_run": dry_run,
        "output": jsonable_tail(result),
        **result,
    }


def jsonable_tail(result: dict[str, Any]) -> str:
    """Return a compact restore output string for existing API clients."""
    return json.dumps(result, default=str, sort_keys=True)[-2000:]


def _handle_restore_failure(source_id: str, error_msg: str) -> dict[str, Any]:
    """Handle restore failure."""
    logger.error("restore_backup_failed", source_id=source_id, error=error_msg[:200])
    return {"status": "failed", "error": error_msg}
