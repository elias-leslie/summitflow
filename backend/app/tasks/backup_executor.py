"""Core backup execution logic."""

from __future__ import annotations

import hmac
from datetime import UTC, datetime
from pathlib import Path

from ..logging_config import get_logger
from ..storage import backups as backup_store
from ..storage.notifications import create_notification
from .backup_lock import acquire_backup_lock, maintain_backup_lock
from .backup_native import BACKUP_TIMEOUT, run_project_backup
from .backup_native_archive import archive_sha256
from .backup_native_offsite import replicate_completed_archive
from .backup_native_restore import restore_isolated_archive
from .backup_utils import (
    as_mapping,
    build_storage_env,
    build_verification_kwargs,
    get_bool_field,
    get_int_field,
    get_project_root,
    get_source_path,
    get_str_field,
    require_verified_backup_output,
)

logger = get_logger(__name__)


def sync_backup_offsite(backup_id: str) -> dict[str, object]:
    """Retry offsite replication from a completed retained local archive."""
    backup = backup_store.get_backup(backup_id)
    if not backup:
        raise FileNotFoundError(f"Backup {backup_id} not found")
    if backup.get("status") not in {"completed", "completed_pending_upload"}:
        raise RuntimeError("Only completed backups can be synced offsite")
    source_id = str(backup.get("source_id") or backup.get("project_id") or "")
    source = backup_store.get_source(source_id)
    if not source:
        raise RuntimeError(f"Backup source {source_id} not found")
    source_path = Path(str(source.get("path") or ""))
    archive_name = str(backup.get("name") or "")
    recorded_location = Path(str(backup.get("location") or ""))
    archive_candidates = (
        recorded_location,
        source_path / "backups" / archive_name,
        source_path / "backups" / "infrastructure" / archive_name,
    )
    archive = next((path for path in archive_candidates if path.is_file()), archive_candidates[1])
    if not archive.is_file():
        raise FileNotFoundError(f"Retained local archive not found: {archive_name}")
    backup_store.merge_backup_verification_json(
        backup_id,
        {"offsite": {"status": "pending"}},
    )
    result = replicate_completed_archive(
        archive,
        source_id=source_id,
        local_dir=archive.parent,
        env=build_storage_env(source_id),
        retention_days=int(source.get("retention_days") or 14),
        retry=True,
    )
    updated = backup_store.merge_backup_verification_json(
        backup_id,
        {"offsite": result},
    )
    return updated or {**backup, "verification_json": {"offsite": result}}


def restore_backup_isolated(
    backup_id: str,
    destination: Path,
    *,
    expected_source_id: str | None = None,
    archive_file: Path | None = None,
) -> dict[str, object]:
    """Restore one retained archive in isolation and persist drill evidence."""
    backup = backup_store.get_backup(backup_id)
    if not backup:
        raise FileNotFoundError(f"Backup {backup_id} not found")
    source_id = str(backup.get("source_id") or backup.get("project_id") or "")
    if expected_source_id and source_id != expected_source_id:
        raise RuntimeError(
            f"Backup {backup_id} belongs to source {source_id}, not {expected_source_id}"
        )
    source = backup_store.get_source(source_id)
    if not source:
        raise RuntimeError(f"Backup source {source_id} not found")
    source_path = Path(str(source.get("path") or ""))
    archive_name = str(backup.get("name") or "")
    recorded_location = Path(str(backup.get("location") or ""))
    archive_candidates = (
        recorded_location,
        source_path / "backups" / archive_name,
        source_path / "backups" / "infrastructure" / archive_name,
    )
    archive = (
        archive_file.expanduser()
        if archive_file is not None
        else next((path for path in archive_candidates if path.is_file()), archive_candidates[1])
    )
    expected_checksum = str(backup.get("checksum") or "")
    if archive_file is not None and not expected_checksum:
        raise RuntimeError("Downloaded archive has no recorded checksum; isolated restore refused")
    if not archive.is_file():
        raise FileNotFoundError(f"Backup archive not found: {archive}")
    if expected_checksum and not hmac.compare_digest(archive_sha256(archive), expected_checksum):
        raise RuntimeError("Archive checksum mismatch: refusing isolated restore")
    verified_at = datetime.now(UTC).isoformat()
    try:
        result = restore_isolated_archive(archive, destination)
        evidence: dict[str, object] = {
            "ok": True,
            "verified_at": verified_at,
            "archive_checksum": backup.get("checksum"),
            "git_restored": bool((result.get("recovery") or {}).get("git_restored")),
            "database_copy_preserved": bool(result.get("database_copy")),
        }
    except Exception as exc:
        backup_store.merge_backup_verification_json(
            backup_id,
            {"isolated_restore": {"ok": False, "verified_at": verified_at, "error": str(exc)}},
        )
        raise
    backup_store.merge_backup_verification_json(
        backup_id,
        {"isolated_restore": evidence},
    )
    return {**result, "evidence": evidence}


def create_backup(
    project_id: str,
    note: str | None = None,
    backup_type: str = "manual",
    keep_local: bool = False,
    local_only: bool = False,
    retention_days: int | None = None,
    source_id: str | None = None,
) -> dict[str, object]:
    """Create a backup for a source through the native backup engine."""
    resolved_source_id = source_id or project_id
    logger.info("create_backup_started", source_id=resolved_source_id, backup_type=backup_type)

    # Route infrastructure sources to dedicated handler
    from .backup_utils import get_source_type

    source_type = get_source_type(resolved_source_id)
    if source_type == "infrastructure":
        from .backup_infra import create_infra_backup

        return create_infra_backup(
            source_id=resolved_source_id,
            note=note,
            backup_type=backup_type,
            keep_local=keep_local,
            retention_days=retention_days,
        )

    backup_dir = get_source_path(resolved_source_id) if source_id else None
    if not backup_dir:
        backup_dir = get_project_root(project_id)
    if not backup_dir:
        error_msg = f"Source {resolved_source_id} not found or has no path"
        logger.error("create_backup_failed", source_id=resolved_source_id, error=error_msg)
        return {"status": "failed", "error": error_msg}

    owner_token = acquire_backup_lock(resolved_source_id)
    if owner_token is None:
        logger.info("create_backup_skipped_locked", source_id=resolved_source_id)
        return {"status": "skipped", "error": f"Backup already running for {resolved_source_id}"}

    return _run_backup(
        project_id,
        backup_dir,
        note,
        backup_type,
        keep_local,
        local_only,
        retention_days,
        resolved_source_id,
        owner_token,
    )


def _run_backup(
    project_id: str,
    project_dir: str,
    note: str | None,
    backup_type: str,
    keep_local: bool,
    local_only: bool,
    retention_days: int | None = None,
    source_id: str | None = None,
    owner_token: str | None = None,
) -> dict[str, object]:
    """Execute backup with lock already held."""
    resolved_source_id = source_id or project_id
    backup_id: str | None = None

    try:
        if owner_token is None:
            raise RuntimeError("Backup lock owner token is required")
        with maintain_backup_lock(resolved_source_id, owner_token):
            backup_record = backup_store.create_backup_record(
                project_id=project_id,
                backup_type=backup_type,
                note=note,
                source_id=source_id,
            )
            backup_id = str(backup_record["id"])
            backup_store.update_backup_status(backup_id, "running")

            parsed_output = run_project_backup(
                project_dir=project_dir,
                source_id=resolved_source_id,
                env=build_storage_env(resolved_source_id),
                keep_local=keep_local,
                local_only=local_only,
                retention_days=retention_days,
            )
            require_verified_backup_output(parsed_output)
    except TimeoutError:
        if backup_id is None:
            return {
                "status": "failed",
                "error": f"Backup timed out after {BACKUP_TIMEOUT // 60} minutes",
                "project_id": project_id,
            }
        return _handle_backup_failure(
            backup_id, f"Backup timed out after {BACKUP_TIMEOUT // 60} minutes", project_id
        )
    except Exception as e:
        if backup_id is None:
            logger.error(
                "create_backup_failed_before_record",
                project_id=project_id,
                error=str(e),
            )
            return {"status": "failed", "error": str(e), "project_id": project_id}
        return _handle_backup_failure(backup_id, str(e), project_id)

    if parsed_output.get("pending_path"):
        return _handle_backup_pending(backup_id, project_id, parsed_output)
    return _handle_backup_success(backup_id, project_id, parsed_output)


def _handle_backup_success(
    backup_id: str,
    project_id: str,
    parsed_output: dict[str, object],
) -> dict[str, object]:
    """Handle successful backup completion."""
    size_info = dict(parsed_output)
    verification_raw = size_info.pop("verification", None)
    verification = as_mapping(verification_raw)
    archive_name = str(size_info.pop("archive_name", "") or "")
    size_info.pop("pending_path", None)
    vkw = build_verification_kwargs(verification) if verification else {}
    backup_store.update_backup_status(
        backup_id, "completed",
        name=archive_name or None,
        size_bytes=get_int_field(size_info, "total_bytes"),
        db_size_bytes=get_int_field(size_info, "db_bytes"),
        files_size_bytes=get_int_field(size_info, "files_bytes"),
        location=get_str_field(size_info, "location"),
        **vkw,
    )
    logger.info(
        "create_backup_completed", backup_id=backup_id, project_id=project_id,
        size_bytes=get_int_field(size_info, "total_bytes"),
        verified=get_bool_field(verification, "verified") if verification else None,
    )
    return {"status": "completed", "backup_id": backup_id, "project_id": project_id, **size_info}


def _handle_backup_pending(
    backup_id: str,
    project_id: str,
    parsed_output: dict[str, object],
) -> dict[str, object]:
    """Handle backups that completed locally but are still pending SMB upload."""
    size_info = dict(parsed_output)
    verification_raw = size_info.pop("verification", None)
    verification = as_mapping(verification_raw)
    archive_name = str(size_info.pop("archive_name", "") or "")
    pending_path = str(size_info.get("pending_path", "") or "")
    vkw = build_verification_kwargs(verification) if verification else {}
    backup_store.update_backup_status(
        backup_id,
        "completed_pending_upload",
        name=archive_name or None,
        size_bytes=get_int_field(size_info, "total_bytes"),
        db_size_bytes=get_int_field(size_info, "db_bytes"),
        files_size_bytes=get_int_field(size_info, "files_bytes"),
        location=pending_path or "pending_upload",
        **vkw,
    )
    logger.info(
        "create_backup_pending_upload",
        backup_id=backup_id,
        project_id=project_id,
        pending_path=pending_path or None,
    )
    return {
        "status": "completed_pending_upload",
        "backup_id": backup_id,
        "project_id": project_id,
        "location": pending_path or "pending_upload",
        "message": "Backup saved locally, pending SMB upload",
        **size_info,
    }


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
