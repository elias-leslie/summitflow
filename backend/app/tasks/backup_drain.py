"""Drain pending backup uploads to SMB."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, cast

from ..logging_config import get_logger
from ..storage import backups as backup_store
from .backup_native import drain_pending_archives

logger = get_logger(__name__)


def drain_pending_backups(dry_run: bool = False) -> dict[str, Any]:
    """Upload pending backups through the native backup engine, then reconcile DB records.

    Args:
        dry_run: If True, only report what would be drained without uploading.

    Returns:
        Summary with counts of uploaded/promoted/remaining records.
    """
    pending_before = backup_store.get_pending_upload_backups()
    pending_count = len(pending_before)
    archive_result = drain_pending_archives(dry_run=True) if dry_run else None
    file_pending = int((archive_result or {}).get("pending_before") or 0)

    if pending_count == 0 and file_pending == 0:
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
        }

    if dry_run:
        return {
            "status": "dry_run",
            "message": f"{pending_count} DB backup(s), {file_pending} file(s) pending upload",
            "pending_before": pending_count,
            "file_pending": file_pending,
            "backups": [
                {
                    "id": b["id"],
                    "source_id": b["source_id"],
                    "name": b.get("name"),
                    "location": b.get("location"),
                    "size_bytes": b.get("size_bytes"),
                }
                for b in pending_before
            ],
            "archives": (archive_result or {}).get("backups", []),
        }

    upload_result = drain_pending_archives(dry_run=False)

    # Reconcile: check which pending backups are no longer in the pending dir
    uploaded_locations = upload_result.get("uploaded_archives")
    promoted = _reconcile_pending_records(
        pending_before,
        uploaded_locations if isinstance(uploaded_locations, dict) else {},
    )

    pending_after = backup_store.get_pending_upload_backups()
    upload_status = str(upload_result.get("status") or "")
    file_remaining = int(upload_result.get("remaining") or 0)
    db_remaining = len(pending_after)
    remaining = max(db_remaining, file_remaining)
    status = "success" if upload_status == "success" and db_remaining == 0 else "partial"
    failures = upload_result.get("failures", [])

    return {
        "status": status,
        "message": upload_result.get("message", "Drain completed"),
        "pending_before": pending_count,
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
