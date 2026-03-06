"""Core backup execution logic."""

from __future__ import annotations

import subprocess
from pathlib import Path

from ..logging_config import get_logger
from ..storage import backups as backup_store
from ..storage.notifications import create_notification
from .backup_lock import acquire_backup_lock, release_backup_lock
from .backup_utils import (
    build_script_error_message,
    build_verification_kwargs,
    get_project_root,
    get_source_path,
    parse_backup_output,
)

logger = get_logger(__name__)

SCRIPT_DIR = Path.home() / "summitflow" / "scripts"
BACKUP_SCRIPT = SCRIPT_DIR / "backup.sh"
BACKUP_TIMEOUT = 600


def create_backup(
    project_id: str,
    note: str | None = None,
    backup_type: str = "manual",
    keep_local: bool = False,
    retention_days: int | None = None,
    source_id: str | None = None,
) -> dict[str, object]:
    """Create a backup for a source. Wraps the existing backup.sh script."""
    resolved_source_id = source_id or project_id
    logger.info("create_backup_started", source_id=resolved_source_id, backup_type=backup_type)

    backup_dir = get_source_path(resolved_source_id) if source_id else None
    if not backup_dir:
        backup_dir = get_project_root(project_id)
    if not backup_dir:
        error_msg = f"Source {resolved_source_id} not found or has no path"
        logger.error("create_backup_failed", source_id=resolved_source_id, error=error_msg)
        return {"status": "failed", "error": error_msg}

    if not acquire_backup_lock(resolved_source_id):
        logger.info("create_backup_skipped_locked", source_id=resolved_source_id)
        return {"status": "skipped", "error": f"Backup already running for {resolved_source_id}"}

    try:
        return _run_backup(
            project_id, backup_dir, note, backup_type, keep_local, retention_days, resolved_source_id
        )
    finally:
        release_backup_lock(resolved_source_id)


def _run_backup(
    project_id: str,
    project_dir: str,
    note: str | None,
    backup_type: str,
    keep_local: bool,
    retention_days: int | None = None,
    source_id: str | None = None,
) -> dict[str, object]:
    """Execute backup with lock already held."""
    backup_record = backup_store.create_backup_record(
        project_id=project_id, backup_type=backup_type, note=note, source_id=source_id
    )
    backup_id = backup_record["id"]
    backup_store.update_backup_status(backup_id, "running")

    cmd = ["bash", str(BACKUP_SCRIPT)]
    if keep_local:
        cmd.append("--keep-local")
    if retention_days is not None:
        cmd.extend(["--retention-days", str(retention_days)])

    try:
        result = subprocess.run(
            cmd, cwd=project_dir, capture_output=True, text=True, timeout=BACKUP_TIMEOUT
        )
        if result.returncode == 0:
            return _handle_backup_success(backup_id, project_id, result.stdout)
        if "SMB unavailable" in result.stdout or "pending" in result.stdout.lower():
            backup_store.update_backup_status(backup_id, "completed", location="pending_upload")
            logger.info("create_backup_pending_upload", backup_id=backup_id, project_id=project_id)
            return {"status": "completed", "backup_id": backup_id, "location": "pending_upload",
                    "message": "Backup saved locally, pending SMB upload"}
        error_msg = build_script_error_message(result)
        logger.error("create_backup_script_failed", backup_id=backup_id,
                     returncode=result.returncode, error=error_msg[:200])
        return _handle_backup_failure(backup_id, error_msg, project_id)
    except subprocess.TimeoutExpired:
        return _handle_backup_failure(
            backup_id, f"Backup timed out after {BACKUP_TIMEOUT // 60} minutes", project_id
        )
    except Exception as e:
        return _handle_backup_failure(backup_id, str(e), project_id)


def _handle_backup_success(backup_id: str, project_id: str, stdout: str) -> dict[str, object]:
    """Handle successful backup completion."""
    size_info = parse_backup_output(stdout)
    verification = size_info.pop("verification", None)
    vkw = build_verification_kwargs(verification) if verification else {}
    backup_store.update_backup_status(
        backup_id, "completed",
        size_bytes=size_info.get("total_bytes"),
        db_size_bytes=size_info.get("db_bytes"),
        files_size_bytes=size_info.get("files_bytes"),
        location=size_info.get("location"),
        **vkw,
    )
    logger.info(
        "create_backup_completed", backup_id=backup_id, project_id=project_id,
        size_bytes=size_info.get("total_bytes"),
        verified=verification.get("verified") if verification else None,
    )
    return {"status": "completed", "backup_id": backup_id, "project_id": project_id, **size_info}


def _handle_backup_failure(backup_id: str, error_msg: str, project_id: str) -> dict[str, object]:
    """Handle backup failure, timeout, or exception."""
    backup_store.update_backup_status(backup_id, "failed", error_message=error_msg)
    logger.error("create_backup_failed", backup_id=backup_id, error=error_msg[:200])
    try:
        backup = backup_store.get_backup(backup_id)
        source_id = backup["source_id"] if backup else "unknown"
        notification_project_id = str(backup.get("project_id") or project_id) if backup else project_id
        create_notification(
            project_id=notification_project_id,
            notification_type="system",
            title=f"Backup failed: {source_id}",
            message=error_msg[:500],
            severity="error",
            metadata={"backup_id": backup_id, "source_id": source_id},
        )
    except Exception:
        logger.warning("backup_failure_notification_failed", backup_id=backup_id)
    return {"status": "failed", "backup_id": backup_id, "error": error_msg}
