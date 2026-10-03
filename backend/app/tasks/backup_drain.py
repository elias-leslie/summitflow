"""Drain pending SMB uploads and retry retained native offsite copies."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, cast

from ..config import get_settings
from ..logging_config import get_logger
from ..storage import backups as backup_store
from .backup_executor import sync_backup_offsite
from .backup_lock import acquire_backup_lock, has_active_backup_lease, maintain_backup_lock
from .backup_native import drain_pending_archives
from .backup_repository_runtime import is_repository_backup
from .backup_utils import as_mapping, build_storage_env, offsite_is_configured

logger = get_logger(__name__)


def drain_pending_backups(dry_run: bool = False) -> dict[str, Any]:
    """Upload pending backups through the native backup engine, then reconcile DB records.

    Args:
        dry_run: If True, only report what would be drained without uploading.

    Returns:
        Summary with counts of uploaded/promoted/remaining records.
    """
    pending_before = _native_records(backup_store.get_pending_upload_backups())
    offsite_before = _native_records(backup_store.get_pending_native_offsite_backups())
    publication_before = backup_store.get_pending_backup_publications() if get_settings().backup_publish_before_backup else []
    pending_count = len(pending_before)
    archive_result = drain_pending_archives(dry_run=True)
    file_pending = int((archive_result or {}).get("pending_before") or 0)

    if pending_count == 0 and file_pending == 0 and not offsite_before and not publication_before:
        return _empty_drain_result()

    if dry_run:
        return _dry_run_result(
            pending_before=pending_before,
            file_pending=file_pending,
            archive_result=archive_result,
            offsite_before=offsite_before,
            publication_before=publication_before,
        )

    publication_result = _retry_pending_publications(publication_before)
    try:
        upload_result = drain_pending_archives(dry_run=False) if pending_count or file_pending else _empty_drain_result()
    except Exception:
        upload_result = {
            "status": "partial", "remaining": file_pending, "failed": 1,
            "failures": [{"name": "SMB pending uploads", "error": "Pending archive drain unavailable"}],
        }
        promoted = 0
    else:
        uploaded_locations = upload_result.get("uploaded_archives")
        promoted = _reconcile_pending_records(
            pending_before,
            uploaded_locations if isinstance(uploaded_locations, dict) else {},
        )

    result = _upload_drain_result(
        pending_before_count=pending_count,
        file_pending=file_pending,
        upload_result=upload_result,
        promoted=promoted,
    )
    # A just-promoted SMB point may now also be eligible for its native replica.
    retries = backup_store.get_pending_native_offsite_backups() if promoted else offsite_before
    offsite_result = _retry_native_offsite_backups(retries)
    result.update(offsite_result)
    result.update(publication_result)
    result["pending_before"] = pending_count + len(offsite_before) + len(publication_before)
    result["uploaded"] += offsite_result["offsite_verified"]
    result["failed"] += offsite_result["offsite_failed"] + publication_result["publication_failed"]
    result["remaining"] += offsite_result["offsite_remaining"] + publication_result["publication_remaining"]
    result["db_remaining"] += offsite_result["offsite_remaining"] + publication_result["publication_remaining"]
    result["failures"] = [*result.get("failures", []), *offsite_result["offsite_failures"], *publication_result["publication_failures"]]
    result["script_output"] = _format_failures(result["failures"])
    if result["remaining"] or result["failed"]:
        result["status"] = "partial"
    if retries or publication_before:
        result["message"] = (
            f"{result['uploaded']} upload(s) verified; {publication_result['publication_completed']} publication retry/retries completed; "
            f"{result['remaining']} pending operation(s) remain"
        )
    return result


def _retry_pending_publications(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Retry durable latest-point publication failures without another capture."""
    from .backup_publish import publication_window_open

    completed = 0
    superseded = 0
    skipped: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for record in records:
        summary = _pending_backup_summary(record)
        if not publication_window_open():
            skipped.append({**summary, "reason": "Outside 02:00-06:00 America/New_York publication window"})
            continue
        source_id = str(record.get("source_id") or record.get("project_id") or "")
        try:
            source = backup_store.get_source(source_id)
            if not source or not source.get("enabled") or source.get("source_type") != "project":
                skipped.append({**summary, "reason": "Project source is no longer enabled"})
                continue
            token = acquire_backup_lock(source_id)
            if token is None:
                skipped.append({**summary, "reason": "A backup or retry owns the source lease"})
                continue
            with maintain_backup_lock(source_id, token):
                latest = backup_store.get_latest_backup(source_id=source_id)
                if (
                    not latest or latest["id"] != record["id"]
                    or ((latest.get("verification_json") or {}).get("publication") or {}).get("status") not in {"failed", "pending"}
                ):
                    skipped.append({**summary, "reason": "Publication evidence was superseded"})
                    superseded += 1
                    continue
                from .backup_publish import publish_source_before_backup

                retained = (latest.get("verification_json") or {}).get("publish_before_backup") or (latest.get("verification_json") or {}).get("publication") or {}
                publication = publish_source_before_backup(source, retained=retained)
                if publication.get("status") not in {"published", "up_to_date", "skipped", "failed", "pending"}:
                    raise RuntimeError("Publication helper returned an unknown status")
                if backup_store.merge_backup_verification_json(str(record["id"]), {
                    "publication": publication, "publish_before_backup": publication,
                }) is None:
                    raise RuntimeError("Publication retry evidence could not be recorded")
                if source.get("project_id"):
                    try:
                        from ..services.publication_health import record_publication_observation
                        record_publication_observation(str(source["project_id"]), publication)
                    except Exception:
                        logger.warning("backup_publication_health_ingestion_unavailable", backup_id=record["id"])
            if publication["status"] in {"published", "up_to_date", "skipped"}:
                completed += 1
            else:
                failures.append({**summary, "error": str(publication.get("reason") or "Publication remains pending")})
        except Exception:
            # Helper outcomes are sanitized; unexpected tool/DB failures must
            # likewise never persist remote credentials or command diagnostics.
            failures.append({**summary, "error": "Publication retry unavailable"})
            logger.warning("backup_publication_auto_retry_failed", backup_id=record["id"])
    return {
        "publication_pending_before": len(records),
        "publication_completed": completed,
        "publication_failed": len(failures),
        "publication_skipped": len(skipped),
        "publication_remaining": len(records) - completed - superseded,
        "publication_failures": failures,
        "publication_skips": skipped,
    }


def _native_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [record for record in records if not is_repository_backup(record)]


def _retry_native_offsite_backups(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Reuse the checksum-guarded retry path; one failure never stops the queue."""
    records = _native_records(records)
    verified = 0
    skipped: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for record in records:
        source_id = str(record.get("source_id") or record.get("project_id") or "")
        summary = _pending_backup_summary(record)
        try:
            backend_id = str(record["storage_backend_id"]) if record.get("storage_backend_id") else None
            try:
                env = build_storage_env(source_id, backend_id) if backend_id else build_storage_env(source_id)
            except ValueError:
                skipped.append({**summary, "reason": "Recorded storage backend is unavailable"})
                continue
            if not offsite_is_configured(env):
                skipped.append({**summary, "reason": "Native offsite destination is not configured"})
                continue
            if has_active_backup_lease(source_id):
                skipped.append({**summary, "reason": "A backup or offsite sync owns the source lease"})
                continue
            # Atomic admission inside sync closes the race after the read-only
            # lease check; it also checks the recorded local checksum under that
            # lease. There is no capture, commit, or publication in this path.
            updated = sync_backup_offsite(str(record["id"]))
            verification = as_mapping(updated.get("verification_json"))
            if verification is None:
                raise RuntimeError("Offsite retry returned no verification evidence")
            offsite = as_mapping(verification.get("offsite"))
            if offsite is None:
                raise RuntimeError("Offsite retry returned no replica verification evidence")
            if offsite.get("status") == "verified":
                verified += 1
            else:
                failures.append({**summary, "error": str(offsite.get("error") or "Offsite verification did not succeed")})
        except Exception as exc:
            failures.append({**summary, "error": str(exc)})
            logger.warning("backup_offsite_auto_retry_failed", backup_id=record["id"], error=str(exc))
    return {
        "offsite_pending_before": len(records),
        "offsite_verified": verified,
        "offsite_failed": len(failures),
        "offsite_skipped": len(skipped),
        "offsite_remaining": len(records) - verified,
        "offsite_failures": failures,
        "offsite_skips": skipped,
    }


def _empty_drain_result() -> dict[str, Any]:
    return {
        "status": "success",
        "message": "No pending uploads to drain",
        "pending_before": 0,
        "file_pending": 0,
        "uploaded": 0,
        "failed": 0,
        "promoted": 0,
        "remaining": 0,
        "db_remaining": 0,
        "file_remaining": 0,
        "offsite_pending_before": 0,
        "offsite_verified": 0,
        "offsite_failed": 0,
        "offsite_skipped": 0,
        "offsite_remaining": 0,
        "offsite_failures": [],
        "offsite_skips": [],
        "publication_pending_before": 0,
        "publication_completed": 0,
        "publication_failed": 0,
        "publication_skipped": 0,
        "publication_remaining": 0,
        "publication_failures": [],
        "publication_skips": [],
    }


def _dry_run_result(
    *,
    pending_before: list[dict[str, Any]],
    file_pending: int,
    archive_result: dict[str, Any] | None,
    offsite_before: list[dict[str, Any]],
    publication_before: list[dict[str, Any]],
) -> dict[str, Any]:
    pending_count = len(pending_before)
    return {
        "status": "dry_run",
        "message": f"{pending_count} SMB backup(s), {len(offsite_before)} offsite copy/copies, "
                   f"{len(publication_before)} publication retry/retries, {file_pending} file(s) pending upload",
        "pending_before": pending_count + len(offsite_before) + len(publication_before),
        "file_pending": file_pending,
        "backups": [_pending_backup_summary(backup) for backup in pending_before],
        "archives": (archive_result or {}).get("backups", []),
        "offsite_pending_before": len(offsite_before),
        "offsite_backups": [_pending_backup_summary(backup) for backup in offsite_before],
        "publication_pending_before": len(publication_before),
        "publication_backups": [_pending_backup_summary(backup) for backup in publication_before],
    }


def _pending_backup_summary(backup: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": backup["id"],
        "source_id": backup.get("source_id") or backup.get("project_id"),
        "name": backup.get("name"),
        "location": backup.get("location"),
        "size_bytes": backup.get("size_bytes"),
    }


def _upload_drain_result(
    *,
    pending_before_count: int,
    file_pending: int,
    upload_result: dict[str, Any],
    promoted: int,
) -> dict[str, Any]:
    pending_after = _native_records(backup_store.get_pending_upload_backups())
    upload_status = str(upload_result.get("status") or "")
    file_remaining = int(upload_result.get("remaining") or 0)
    db_remaining = len(pending_after)
    remaining = max(db_remaining, file_remaining)
    status = "success" if upload_status == "success" and db_remaining == 0 else "partial"
    failures = upload_result.get("failures", [])

    return {
        "status": status,
        "message": upload_result.get("message", "Drain completed"),
        "pending_before": pending_before_count,
        "file_pending": upload_result.get("pending_before", file_pending),
        "uploaded": upload_result.get("uploaded", 0),
        "failed": upload_result.get("failed", 0),
        "promoted": promoted,
        "remaining": remaining,
        "db_remaining": db_remaining,
        "file_remaining": file_remaining,
        "failures": failures,
        "script_output": _format_failures(failures),
    }


def _format_failures(failures: object) -> str:
    if not isinstance(failures, list):
        return ""
    lines = []
    for failure in failures[:10]:
        if not isinstance(failure, dict):
            continue
        item = cast(dict[str, Any], failure)
        name = item.get("name") or "?"
        error = item.get("error") or "unknown error"
        remote_path = item.get("remote_path")
        suffix = f" remote_path={remote_path}" if remote_path else ""
        lines.append(f"{name}: {error}{suffix}")
    return "\n".join(lines)


def _reconcile_pending_records(
    pending_records: list[dict[str, Any]],
    uploaded_locations: dict[str, str] | None = None,
) -> int:
    """Promote pending_upload records whose files are no longer in the pending dir."""
    pending_dir = Path(os.environ.get("HOME", str(Path.home()))) / ".local" / "share" / "backup-pending"
    promoted = 0
    uploaded_locations = uploaded_locations or {}

    smb_host = os.environ.get("SMB_HOST", "")
    smb_share = os.environ.get("SMB_SHARE", "")

    for record in pending_records:
        if is_repository_backup(record):
            continue
        location = record.get("location", "")
        name = record.get("name", "")
        source_id = record.get("source_id", "")

        # Check if the file is still in the pending directory
        still_pending = False
        if location and "backup-pending" in str(location):
            still_pending = Path(location).exists()
        elif name:
            still_pending = (pending_dir / name).exists()

        if not still_pending:
            # Compute SMB location for the promoted record
            smb_location = uploaded_locations.get(str(name)) if name else None
            if smb_host and smb_share and name and source_id:
                smb_location = smb_location or f"//{smb_host}/{smb_share}/project-backups/{source_id}/{name}"

            if backup_store.promote_pending_upload(record["id"], location=smb_location):
                promoted += 1
                logger.info("promoted_pending_backup", backup_id=record["id"], location=smb_location)

    return promoted
