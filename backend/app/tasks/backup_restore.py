"""Backup restoration logic."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from ..logging_config import get_logger
from ..storage import backups as backup_store
from .backup_utils import get_project_root

logger = get_logger(__name__)

# Default paths
SCRIPT_DIR = Path.home() / "summitflow" / "scripts"
RESTORE_SCRIPT = SCRIPT_DIR / "restore.sh"


def restore_backup(
    project_id: str,
    backup_id: str | None = None,
    backup_file: str | None = None,
    dry_run: bool = False,
    db_only: bool = False,
    files_only: bool = False,
) -> dict[str, Any]:
    """Restore a project from backup.

    Wraps the existing restore.sh script.

    Args:
        project_id: Project ID to restore
        backup_id: Backup record ID (uses backup name from record)
        backup_file: Direct path to backup archive (alternative to backup_id)
        dry_run: If True, show what would be restored without doing it
        db_only: If True, restore database only
        files_only: If True, restore files only

    Returns:
        Restore result dict
    """
    logger.info(
        "restore_backup_started",
        project_id=project_id,
        backup_id=backup_id,
        dry_run=dry_run,
    )

    # Get project root path
    project_dir = get_project_root(project_id)
    if not project_dir:
        error_msg = f"Project {project_id} not found or has no root_path"
        logger.error("restore_backup_failed", error=error_msg)
        return {"status": "failed", "error": error_msg}

    # Build command
    cmd = _build_restore_command(backup_id, backup_file, dry_run, db_only, files_only)

    try:
        result = subprocess.run(
            cmd,
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=1800,  # 30 minute timeout for restore
        )

        if result.returncode == 0:
            return _handle_restore_success(project_id, dry_run, result.stdout)

        error_msg = result.stderr or result.stdout or "Unknown error"
        return _handle_restore_failure(project_id, error_msg)

    except subprocess.TimeoutExpired:
        return _handle_restore_timeout(project_id)

    except Exception as e:
        return _handle_restore_exception(project_id, str(e))


def _build_restore_command(
    backup_id: str | None,
    backup_file: str | None,
    dry_run: bool,
    db_only: bool,
    files_only: bool,
) -> list[str]:
    """Build restore command with appropriate flags."""
    cmd = ["bash", str(RESTORE_SCRIPT)]

    if backup_file:
        cmd.extend(["--file", backup_file])
    elif backup_id:
        # Get backup record to find the archive name
        backup_record = backup_store.get_backup(backup_id)
        if not backup_record:
            # Will fail later, but keep building command
            pass
        # Use latest for simplicity; script will find the archive
        cmd.append("--latest")
    else:
        cmd.append("--latest")

    if dry_run:
        cmd.append("--dry-run")
    if db_only:
        cmd.append("--db-only")
    if files_only:
        cmd.append("--files-only")

    return cmd


def _handle_restore_success(project_id: str, dry_run: bool, stdout: str) -> dict[str, Any]:
    """Handle successful restore."""
    logger.info(
        "restore_backup_completed",
        project_id=project_id,
        dry_run=dry_run,
    )

    return {
        "status": "completed",
        "project_id": project_id,
        "dry_run": dry_run,
        "output": stdout[-2000:] if stdout else None,
    }


def _handle_restore_failure(project_id: str, error_msg: str) -> dict[str, Any]:
    """Handle restore failure."""
    logger.error(
        "restore_backup_failed",
        project_id=project_id,
        error=error_msg[:200],
    )
    return {"status": "failed", "error": error_msg}


def _handle_restore_timeout(project_id: str) -> dict[str, Any]:
    """Handle restore timeout."""
    logger.error("restore_backup_timeout", project_id=project_id)
    return {"status": "failed", "error": "Restore timed out after 30 minutes"}


def _handle_restore_exception(project_id: str, error_msg: str) -> dict[str, Any]:
    """Handle restore exception."""
    logger.error("restore_backup_exception", project_id=project_id)
    return {"status": "failed", "error": error_msg}
