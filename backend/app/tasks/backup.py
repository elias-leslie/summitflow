"""Celery tasks for backup and restore operations.

Tasks:
- create_backup: Create a new backup for a project
- restore_backup: Restore from a backup archive
- run_scheduled_backups: Check and run due scheduled backups
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from celery import shared_task

from ..logging_config import get_logger
from ..storage import backups as backup_store
from ..storage.connection import get_connection

logger = get_logger(__name__)

# Default paths
SCRIPT_DIR = Path.home() / "summitflow" / "scripts"
BACKUP_SCRIPT = SCRIPT_DIR / "backup.sh"
RESTORE_SCRIPT = SCRIPT_DIR / "restore.sh"


@shared_task(name="summitflow.create_backup", bind=True)  # type: ignore[untyped-decorator]
def create_backup(
    self: Any,
    project_id: str,
    note: str | None = None,
    backup_type: str = "manual",
    keep_local: bool = False,
) -> dict[str, Any]:
    """Create a backup for a project.

    Wraps the existing backup.sh script.

    Args:
        project_id: Project ID to backup
        note: Optional user note
        backup_type: 'manual' or 'scheduled'
        keep_local: If True, keep local copy in addition to SMB

    Returns:
        Backup record dict
    """
    logger.info(
        "create_backup_started",
        project_id=project_id,
        backup_type=backup_type,
        task_id=self.request.id,
    )

    # Get project root path first to validate project exists
    project_dir = _get_project_root(project_id)
    if not project_dir:
        error_msg = f"Project {project_id} not found or has no root_path"
        logger.error("create_backup_failed", project_id=project_id, error=error_msg)
        return {"status": "failed", "error": error_msg}

    # Create pending backup record
    backup_record = backup_store.create_backup_record(
        project_id=project_id,
        backup_type=backup_type,
        note=note,
    )
    backup_id = backup_record["id"]

    # Mark as running
    backup_store.update_backup_status(backup_id, "running")

    # Build command
    cmd = ["bash", str(BACKUP_SCRIPT)]
    if keep_local:
        cmd.append("--keep-local")

    try:
        # Run backup.sh
        result = subprocess.run(
            cmd,
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=600,  # 10 minute timeout
        )

        if result.returncode == 0:
            # Parse output for size info
            size_info = _parse_backup_output(result.stdout)

            backup_store.update_backup_status(
                backup_id,
                "completed",
                size_bytes=size_info.get("total_bytes"),
                db_size_bytes=size_info.get("db_bytes"),
                files_size_bytes=size_info.get("files_bytes"),
                location=size_info.get("location"),
            )

            logger.info(
                "create_backup_completed",
                backup_id=backup_id,
                project_id=project_id,
                size_bytes=size_info.get("total_bytes"),
            )

            return {
                "status": "completed",
                "backup_id": backup_id,
                "project_id": project_id,
                **size_info,
            }
        else:
            # Check if SMB was unavailable (pending local backup)
            if "SMB unavailable" in result.stdout or "pending" in result.stdout.lower():
                backup_store.update_backup_status(
                    backup_id,
                    "completed",
                    location="pending_upload",
                )
                logger.info(
                    "create_backup_pending_upload",
                    backup_id=backup_id,
                    project_id=project_id,
                )
                return {
                    "status": "completed",
                    "backup_id": backup_id,
                    "location": "pending_upload",
                    "message": "Backup saved locally, pending SMB upload",
                }

            # Actual failure
            error_msg = result.stderr or result.stdout or "Unknown error"
            backup_store.update_backup_status(backup_id, "failed", error_message=error_msg[:500])
            logger.error(
                "create_backup_failed",
                backup_id=backup_id,
                error=error_msg[:200],
            )
            return {"status": "failed", "backup_id": backup_id, "error": error_msg}

    except subprocess.TimeoutExpired:
        error_msg = "Backup timed out after 10 minutes"
        backup_store.update_backup_status(backup_id, "failed", error_message=error_msg)
        logger.error("create_backup_timeout", backup_id=backup_id)
        return {"status": "failed", "backup_id": backup_id, "error": error_msg}

    except Exception as e:
        error_msg = str(e)
        backup_store.update_backup_status(backup_id, "failed", error_message=error_msg[:500])
        logger.error("create_backup_exception", backup_id=backup_id)
        return {"status": "failed", "backup_id": backup_id, "error": error_msg}


@shared_task(name="summitflow.restore_backup", bind=True)  # type: ignore[untyped-decorator]
def restore_backup(
    self: Any,
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
        task_id=self.request.id,
    )

    # Get project root path
    project_dir = _get_project_root(project_id)
    if not project_dir:
        error_msg = f"Project {project_id} not found or has no root_path"
        logger.error("restore_backup_failed", error=error_msg)
        return {"status": "failed", "error": error_msg}

    # Build command
    cmd = ["bash", str(RESTORE_SCRIPT)]

    if backup_file:
        cmd.extend(["--file", backup_file])
    elif backup_id:
        # Get backup record to find the archive name
        backup_record = backup_store.get_backup(backup_id)
        if not backup_record:
            return {"status": "failed", "error": f"Backup {backup_id} not found"}
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

    try:
        result = subprocess.run(
            cmd,
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=1800,  # 30 minute timeout for restore
        )

        if result.returncode == 0:
            logger.info(
                "restore_backup_completed",
                project_id=project_id,
                dry_run=dry_run,
            )

            return {
                "status": "completed",
                "project_id": project_id,
                "dry_run": dry_run,
                "output": result.stdout[-2000:] if result.stdout else None,
            }
        else:
            error_msg = result.stderr or result.stdout or "Unknown error"
            logger.error(
                "restore_backup_failed",
                project_id=project_id,
                error=error_msg[:200],
            )
            return {"status": "failed", "error": error_msg}

    except subprocess.TimeoutExpired:
        logger.error("restore_backup_timeout", project_id=project_id)
        return {"status": "failed", "error": "Restore timed out after 30 minutes"}

    except Exception as e:
        logger.error("restore_backup_exception", project_id=project_id)
        return {"status": "failed", "error": str(e)}


@shared_task(name="summitflow.run_scheduled_backups")  # type: ignore[untyped-decorator]
def run_scheduled_backups() -> dict[str, Any]:
    """Check and run due scheduled backups.

    Queries backup_schedules for any that are due and triggers backups.

    Returns:
        Summary of scheduled backups run
    """
    logger.info("run_scheduled_backups_started")

    due_schedules = backup_store.list_due_schedules()

    if not due_schedules:
        logger.info("no_scheduled_backups_due")
        return {"status": "success", "message": "No scheduled backups due", "count": 0}

    results: list[dict[str, Any]] = []

    for schedule in due_schedules:
        project_id = schedule["project_id"]
        frequency = schedule["frequency"]

        logger.info(
            "triggering_scheduled_backup",
            project_id=project_id,
            frequency=frequency,
        )

        # Trigger backup task
        task = create_backup.delay(
            project_id=project_id,
            backup_type="scheduled",
            note=f"Scheduled {frequency} backup",
        )

        # Calculate next run time
        next_run = _calculate_next_run(frequency)
        backup_store.update_schedule_last_run(project_id, next_run)

        results.append(
            {
                "project_id": project_id,
                "task_id": task.id,
                "next_run": next_run.isoformat() if next_run else None,
            }
        )

    logger.info("run_scheduled_backups_completed", count=len(results))

    return {
        "status": "success",
        "count": len(results),
        "results": results,
    }


def _get_project_root(project_id: str) -> str | None:
    """Get root_path for a project."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT root_path FROM projects WHERE id = %s",
            (project_id,),
        )
        row = cur.fetchone()
        return row[0] if row and row[0] else None


def _parse_backup_output(output: str) -> dict[str, Any]:
    """Parse backup.sh output for size and location info."""
    result: dict[str, Any] = {}

    for line in output.split("\n"):
        line = line.strip()
        if line.startswith("Size:"):
            # Parse "Size: 123M" or "Size: 123456 bytes"
            size_str = line.split(":", 1)[1].strip()
            result["total_bytes"] = _parse_size(size_str)
        elif line.startswith("DB Size:"):
            size_str = line.split(":", 1)[1].strip()
            result["db_bytes"] = _parse_size(size_str)
        elif line.startswith("Location:"):
            result["location"] = line.split(":", 1)[1].strip()

    return result


def _parse_size(size_str: str) -> int | None:
    """Parse size string like '123M', '1.5G', or '123456 bytes'."""
    size_str = size_str.strip()

    if "bytes" in size_str:
        try:
            return int(size_str.replace("bytes", "").strip())
        except ValueError:
            return None

    multipliers = {"K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4}

    for suffix, mult in multipliers.items():
        if size_str.endswith(suffix):
            try:
                return int(float(size_str[:-1]) * mult)
            except ValueError:
                return None

    try:
        return int(size_str)
    except ValueError:
        return None


def _calculate_next_run(frequency: str) -> datetime:
    """Calculate next run time based on frequency."""
    now = datetime.now(UTC)

    if frequency == "daily":
        return now + timedelta(days=1)
    elif frequency == "weekly":
        return now + timedelta(weeks=1)
    elif frequency == "monthly":
        return now + timedelta(days=30)
    else:
        # Default to daily
        return now + timedelta(days=1)
