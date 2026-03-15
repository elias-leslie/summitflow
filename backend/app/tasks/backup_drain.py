"""Drain pending backup uploads to SMB."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from ..logging_config import get_logger
from ..storage import backups as backup_store

logger = get_logger(__name__)

_HOST_ROOT = os.environ.get("BACKUP_HOST_ROOT")
SCRIPT_DIR = Path(_HOST_ROOT) / "summitflow" / "scripts" if _HOST_ROOT else Path.home() / "summitflow" / "scripts"
PENDING_UPLOAD_SCRIPT = SCRIPT_DIR / "backup-pending-upload.sh"
DRAIN_TIMEOUT = 600


def drain_pending_backups(dry_run: bool = False) -> dict[str, Any]:
    """Upload pending backups via backup-pending-upload.sh, then reconcile DB records.

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

    # Run the upload script
    upload_result = _run_upload_script()

    # Reconcile: check which pending backups are no longer in the pending dir
    promoted = _reconcile_pending_records(pending_before)

    pending_after = backup_store.get_pending_upload_backups()

    return {
        "status": "success" if upload_result["ok"] else "partial",
        "message": upload_result.get("message", "Drain completed"),
        "pending_before": pending_count,
        "uploaded": upload_result.get("uploaded", 0),
        "promoted": promoted,
        "remaining": len(pending_after),
        "script_output": upload_result.get("output", "")[-500:],
    }


def _run_upload_script() -> dict[str, Any]:
    """Execute backup-pending-upload.sh and return result."""
    if not PENDING_UPLOAD_SCRIPT.exists():
        logger.error("pending_upload_script_missing", path=str(PENDING_UPLOAD_SCRIPT))
        return {"ok": False, "message": f"Script not found: {PENDING_UPLOAD_SCRIPT}"}

    try:
        result = subprocess.run(
            ["bash", str(PENDING_UPLOAD_SCRIPT)],
            capture_output=True,
            text=True,
            timeout=DRAIN_TIMEOUT,
        )
        ok = result.returncode == 0
        output = result.stdout + result.stderr
        logger.info(
            "pending_upload_script_result",
            returncode=result.returncode,
            output_len=len(output),
        )
        return {"ok": ok, "output": output, "message": "Upload script completed" if ok else "Upload script failed"}
    except subprocess.TimeoutExpired:
        logger.error("pending_upload_script_timeout")
        return {"ok": False, "message": f"Upload script timed out after {DRAIN_TIMEOUT}s"}
    except Exception as e:
        logger.error("pending_upload_script_error", error=str(e))
        return {"ok": False, "message": str(e)}


def _reconcile_pending_records(pending_records: list[dict[str, Any]]) -> int:
    """Promote pending_upload records whose files are no longer in the pending dir."""
    pending_dir = Path(os.environ.get("HOME", str(Path.home()))) / ".local" / "share" / "backup-pending"
    promoted = 0

    for record in pending_records:
        location = record.get("location", "")
        name = record.get("name", "")

        # Check if the file is still in the pending directory
        still_pending = False
        if location and "backup-pending" in str(location):
            still_pending = Path(location).exists()
        elif name:
            still_pending = (pending_dir / name).exists()

        if not still_pending and backup_store.promote_pending_upload(record["id"]):
                promoted += 1
                logger.info("promoted_pending_backup", backup_id=record["id"])

    return promoted
