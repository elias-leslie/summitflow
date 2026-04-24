"""Drain pending backup uploads to SMB."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

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

    if pending_count == 0:
        return {
            "status": "success",
            "message": "No pending uploads to drain",
            "pending_before": 0,
            "uploaded": 0,
            "promoted": 0,
            "remaining": 0,
        }

    if dry_run:
        return {
            "status": "dry_run",
            "message": f"{pending_count} backup(s) pending upload",
            "pending_before": pending_count,
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
        }

    upload_result = drain_pending_archives(dry_run=False)

    # Reconcile: check which pending backups are no longer in the pending dir
    promoted = _reconcile_pending_records(pending_before)

    pending_after = backup_store.get_pending_upload_backups()
    upload_status = str(upload_result.get("status") or "")

    return {
        "status": "success" if upload_status == "success" else "partial",
        "message": upload_result.get("message", "Drain completed"),
        "pending_before": pending_count,
        "uploaded": upload_result.get("uploaded", 0),
        "promoted": promoted,
        "remaining": len(pending_after),
        "script_output": "",
    }


def _reconcile_pending_records(pending_records: list[dict[str, Any]]) -> int:
    """Promote pending_upload records whose files are no longer in the pending dir."""
    pending_dir = Path(os.environ.get("HOME", str(Path.home()))) / ".local" / "share" / "backup-pending"
    promoted = 0

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
            smb_location = None
            if smb_host and smb_share and name and source_id:
                smb_location = f"//{smb_host}/{smb_share}/project-backups/{source_id}/{name}"

            if backup_store.promote_pending_upload(record["id"], location=smb_location):
                promoted += 1
                logger.info("promoted_pending_backup", backup_id=record["id"], location=smb_location)

    return promoted
