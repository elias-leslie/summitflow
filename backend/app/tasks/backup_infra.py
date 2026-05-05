"""Infrastructure backup execution logic."""

from __future__ import annotations

from ..logging_config import get_logger
from ..storage import backups as backup_store
from ..storage.notifications import create_notification
from .backup_lock import acquire_backup_lock, release_backup_lock
from .backup_native import INFRA_BACKUP_TIMEOUT, run_infra_backup
from .backup_utils import (
    as_mapping,
    build_storage_env,
    build_verification_kwargs,
    get_int_field,
    get_str_field,
)

logger = get_logger(__name__)

def create_infra_backup(
    source_id: str = "infrastructure",
    note: str | None = None,
    backup_type: str = "manual",
    keep_local: bool = False,
    retention_days: int | None = None,
) -> dict[str, object]:
    """Create an infrastructure backup (pg_dumpall + configs)."""
    logger.info("create_infra_backup_started", source_id=source_id, backup_type=backup_type)

    if not acquire_backup_lock(source_id):
        logger.info("create_infra_backup_skipped_locked", source_id=source_id)
        return {"status": "skipped", "error": f"Backup already running for {source_id}"}

    try:
        return _run_infra_backup(source_id, note, backup_type, keep_local, retention_days)
    finally:
        release_backup_lock(source_id)


def _run_infra_backup(
    source_id: str,
    note: str | None,
    backup_type: str,
    keep_local: bool,
    retention_days: int | None,
) -> dict[str, object]:
    """Execute infrastructure backup with lock held."""
    # Use a pseudo project_id for infrastructure
    project_id = "infrastructure"

    backup_record = backup_store.create_backup_record(
        project_id=project_id, backup_type=backup_type, note=note, source_id=source_id
    )
    backup_id = backup_record["id"]
    backup_store.update_backup_status(backup_id, "running")

    try:
        parsed_output = run_infra_backup(
            env=build_storage_env(source_id),
            keep_local=keep_local,
            retention_days=retention_days,
        )
        if parsed_output.get("pending_path"):
            return _handle_pending(backup_id, parsed_output)
        return _handle_success(backup_id, parsed_output)
    except TimeoutError:
        return _handle_failure(backup_id, f"Infrastructure backup timed out after {INFRA_BACKUP_TIMEOUT // 60} minutes")
    except Exception as e:
        return _handle_failure(backup_id, str(e))


def _handle_success(backup_id: str, parsed: dict[str, object]) -> dict[str, object]:
    """Handle successful infrastructure backup."""
    info = dict(parsed)
    verification_raw = info.pop("verification", None)
    verification = as_mapping(verification_raw)
    archive_name = str(info.pop("archive_name", "") or "")
    info.pop("pending_path", None)
    vkw = build_verification_kwargs(verification) if verification else {}

    backup_store.update_backup_status(
        backup_id, "completed",
        name=archive_name or None,
        size_bytes=get_int_field(info, "total_bytes"),
        db_size_bytes=get_int_field(info, "db_bytes"),
        files_size_bytes=get_int_field(info, "files_bytes"),
        location=get_str_field(info, "location"),
        **vkw,
    )
    logger.info("create_infra_backup_completed", backup_id=backup_id)
    return {"status": "completed", "backup_id": backup_id, **info}


def _handle_pending(backup_id: str, parsed: dict[str, object]) -> dict[str, object]:
    """Handle infrastructure backup pending SMB upload."""
    info = dict(parsed)
    verification_raw = info.pop("verification", None)
    verification = as_mapping(verification_raw)
    archive_name = str(info.pop("archive_name", "") or "")
    pending_path = str(info.get("pending_path", "") or "")
    vkw = build_verification_kwargs(verification) if verification else {}

    backup_store.update_backup_status(
        backup_id, "completed_pending_upload",
        name=archive_name or None,
        size_bytes=get_int_field(info, "total_bytes"),
        db_size_bytes=get_int_field(info, "db_bytes"),
        files_size_bytes=get_int_field(info, "files_bytes"),
        location=pending_path or "pending_upload",
        **vkw,
    )
    logger.info("create_infra_backup_pending", backup_id=backup_id, pending_path=pending_path)
    return {"status": "completed_pending_upload", "backup_id": backup_id, "location": pending_path or "pending_upload", **info}


def _handle_failure(backup_id: str, error_msg: str) -> dict[str, object]:
    """Handle infrastructure backup failure."""
    backup_store.update_backup_status(backup_id, "failed", error_message=error_msg)
    logger.error("create_infra_backup_failed", backup_id=backup_id, error=error_msg[:200])
    try:
        create_notification(
            project_id="infrastructure",
            notification_type="system",
            title="Infrastructure backup failed",
            message=error_msg[:500],
            severity="error",
            metadata={"backup_id": backup_id, "source_id": "infrastructure"},
        )
    except Exception:
        logger.warning("infra_backup_failure_notification_failed", backup_id=backup_id)
    return {"status": "failed", "backup_id": backup_id, "error": error_msg}
