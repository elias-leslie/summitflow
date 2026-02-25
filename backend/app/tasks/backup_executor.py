"""Core backup execution logic."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from ..logging_config import get_logger
from ..storage import backups as backup_store
from .backup_lock import acquire_backup_lock, release_backup_lock
from .backup_utils import get_project_root, get_source_path, parse_backup_output

logger = get_logger(__name__)

# Default paths
SCRIPT_DIR = Path.home() / "summitflow" / "scripts"
BACKUP_SCRIPT = SCRIPT_DIR / "backup.sh"


def create_backup(
    project_id: str,
    note: str | None = None,
    backup_type: str = "manual",
    keep_local: bool = False,
    retention_days: int | None = None,
    source_id: str | None = None,
) -> dict[str, Any]:
    """Create a backup for a source.

    Wraps the existing backup.sh script.

    Args:
        project_id: Project ID to backup
        note: Optional user note
        backup_type: 'manual' or 'scheduled'
        keep_local: If True, keep local copy in addition to SMB
        retention_days: Days to retain backups (overrides default)
        source_id: Backup source ID (defaults to project_id)

    Returns:
        Backup record dict
    """
    resolved_source_id = source_id or project_id

    logger.info(
        "create_backup_started",
        source_id=resolved_source_id,
        backup_type=backup_type,
    )

    # Resolve backup directory: try source path first, then project root
    backup_dir = get_source_path(resolved_source_id) if source_id else None
    if not backup_dir:
        backup_dir = get_project_root(project_id)
    if not backup_dir:
        error_msg = f"Source {resolved_source_id} not found or has no path"
        logger.error("create_backup_failed", source_id=resolved_source_id, error=error_msg)
        return {"status": "failed", "error": error_msg}

    # Acquire per-source lock to prevent concurrent backups
    if not acquire_backup_lock(resolved_source_id):
        logger.info(
            "create_backup_skipped_locked",
            source_id=resolved_source_id,
        )
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
) -> dict[str, Any]:
    """Execute backup with lock already held."""
    # Create pending backup record
    backup_record = backup_store.create_backup_record(
        project_id=project_id,
        backup_type=backup_type,
        note=note,
        source_id=source_id,
    )
    backup_id = backup_record["id"]

    # Mark as running
    backup_store.update_backup_status(backup_id, "running")

    # Build command
    cmd = ["bash", str(BACKUP_SCRIPT)]
    if keep_local:
        cmd.append("--keep-local")
    if retention_days is not None:
        cmd.extend(["--retention-days", str(retention_days)])

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
            return _handle_backup_success(backup_id, project_id, result.stdout)

        # Check if SMB was unavailable (pending local backup)
        if "SMB unavailable" in result.stdout or "pending" in result.stdout.lower():
            return _handle_pending_upload(backup_id, project_id)

        # Actual failure — build informative error from rc + stderr + stdout
        stderr_clean = result.stderr or ""
        # Filter smbclient progress lines (e.g. "putting file ...")
        stderr_lines = [
            line
            for line in stderr_clean.splitlines()
            if not line.strip().startswith("putting file")
        ]
        stderr_filtered = "\n".join(stderr_lines).strip()
        stdout_tail = (result.stdout or "")[-500:].strip()

        parts = [f"rc={result.returncode}"]
        if stderr_filtered:
            parts.append(f"stderr: {stderr_filtered}")
        if stdout_tail:
            parts.append(f"stdout(tail): {stdout_tail}")
        error_msg = " | ".join(parts) if any([stderr_filtered, stdout_tail]) else "Unknown error"

        logger.error(
            "create_backup_script_failed",
            backup_id=backup_id,
            returncode=result.returncode,
            stderr=stderr_filtered[:200],
            stdout_tail=stdout_tail[:200],
        )
        return _handle_backup_failure(backup_id, error_msg)

    except subprocess.TimeoutExpired:
        return _handle_backup_timeout(backup_id)

    except Exception as e:
        return _handle_backup_exception(backup_id, str(e))


def _handle_backup_success(backup_id: str, project_id: str, stdout: str) -> dict[str, Any]:
    """Handle successful backup completion."""
    # Parse output for size and verification info
    size_info = parse_backup_output(stdout)
    verification = size_info.pop("verification", None)

    verification_kwargs: dict[str, Any] = {}
    if verification:
        verification_kwargs["verified"] = verification.get("verified")
        verification_kwargs["verified_at"] = verification.get("verified_at")
        verification_kwargs["checksum"] = verification.get("checksum")
        total = verification.get("total_files")
        if total is not None:
            verification_kwargs["total_files"] = int(total)
        verification_kwargs["verification_json"] = verification

    backup_store.update_backup_status(
        backup_id,
        "completed",
        size_bytes=size_info.get("total_bytes"),
        db_size_bytes=size_info.get("db_bytes"),
        files_size_bytes=size_info.get("files_bytes"),
        location=size_info.get("location"),
        **verification_kwargs,
    )

    logger.info(
        "create_backup_completed",
        backup_id=backup_id,
        project_id=project_id,
        size_bytes=size_info.get("total_bytes"),
        verified=verification.get("verified") if verification else None,
    )

    return {
        "status": "completed",
        "backup_id": backup_id,
        "project_id": project_id,
        **size_info,
    }


def _handle_pending_upload(backup_id: str, project_id: str) -> dict[str, Any]:
    """Handle backup saved locally but pending SMB upload."""
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


def _handle_backup_failure(backup_id: str, error_msg: str) -> dict[str, Any]:
    """Handle backup failure."""
    backup_store.update_backup_status(backup_id, "failed", error_message=error_msg)
    logger.error(
        "create_backup_failed",
        backup_id=backup_id,
        error=error_msg[:200],
    )
    return {"status": "failed", "backup_id": backup_id, "error": error_msg}


def _handle_backup_timeout(backup_id: str) -> dict[str, Any]:
    """Handle backup timeout."""
    error_msg = "Backup timed out after 10 minutes"
    backup_store.update_backup_status(backup_id, "failed", error_message=error_msg)
    logger.error("create_backup_timeout", backup_id=backup_id)
    return {"status": "failed", "backup_id": backup_id, "error": error_msg}


def _handle_backup_exception(backup_id: str, error_msg: str) -> dict[str, Any]:
    """Handle backup exception."""
    backup_store.update_backup_status(backup_id, "failed", error_message=error_msg)
    logger.error("create_backup_exception", backup_id=backup_id)
    return {"status": "failed", "backup_id": backup_id, "error": error_msg}
