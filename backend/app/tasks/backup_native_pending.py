from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..logging_config import get_logger
from .backup_native_smb import SmbUploadResult, StorageConfig, _storage_from_pending_meta

logger = get_logger(__name__)

SmbUploader = Callable[[Path, str, StorageConfig], SmbUploadResult]


def drain_pending_archives_from_dir(
    pending_dir: Path,
    *,
    dry_run: bool = False,
    uploader: SmbUploader,
) -> dict[str, Any]:
    """Upload pending archives from an explicit pending directory."""
    archives = sorted(pending_dir.glob("*.tar.gz")) if pending_dir.exists() else []
    if not archives:
        return {"status": "success", "message": "No pending uploads to drain", "uploaded": 0, "remaining": 0}
    if dry_run:
        return _pending_dry_run(archives)

    uploaded = 0
    failures: list[dict[str, Any]] = []
    uploaded_archives: dict[str, str] = {}
    for archive in archives:
        upload = _upload_pending_archive(archive, uploader)
        if upload["ok"]:
            uploaded += 1
            uploaded_archives[archive.name] = str(upload["location"])
        else:
            failures.append(upload["failure"])
    remaining = len(list(pending_dir.glob("*.tar.gz"))) if pending_dir.exists() else 0
    return {
        "status": "success" if remaining == 0 else "partial",
        "uploaded": uploaded,
        "failed": len(failures),
        "remaining": remaining,
        "uploaded_archives": uploaded_archives,
        "failures": failures[:20],
        "message": "Pending uploads drained" if remaining == 0 else f"{remaining} pending upload(s) remain",
    }


def _pending_dry_run(archives: list[Path]) -> dict[str, Any]:
    return {
        "status": "dry_run",
        "message": f"{len(archives)} backup(s) pending upload",
        "pending_before": len(archives),
        "backups": [
            {"name": path.name, "location": str(path), "size_bytes": path.stat().st_size}
            for path in archives
        ],
    }


def _upload_pending_archive(archive: Path, uploader: SmbUploader) -> dict[str, Any]:
    meta_path = archive.with_suffix(archive.suffix + ".meta")
    if not meta_path.exists():
        logger.warning("backup_pending_missing_metadata", archive=archive.name, path=str(archive))
        return {"ok": False, "failure": _failure(archive, "missing metadata file")}
    try:
        meta = json.loads(meta_path.read_text())
    except json.JSONDecodeError as exc:
        logger.warning("backup_pending_invalid_metadata", archive=archive.name, error=str(exc))
        return {"ok": False, "failure": _failure(archive, f"invalid metadata JSON: {exc}")}

    storage = _storage_from_pending_meta(meta, archive)
    upload = uploader(archive, archive.name, storage)
    if upload.ok:
        archive.unlink(missing_ok=True)
        meta_path.unlink(missing_ok=True)
        return {"ok": True, "location": upload.location}

    _record_upload_failure(meta_path, meta, storage, upload)
    logger.warning(
        "backup_pending_upload_failed",
        archive=archive.name,
        remote_path=storage.remote_path,
        returncode=upload.returncode,
        error=upload.error,
    )
    return {
        "ok": False,
        "failure": {
            "name": archive.name,
            "location": str(archive),
            "remote_path": storage.remote_path,
            "returncode": upload.returncode,
            "error": upload.error,
        },
    }


def _failure(archive: Path, error: str) -> dict[str, str]:
    return {"name": archive.name, "location": str(archive), "error": error}


def _record_upload_failure(
    meta_path: Path,
    meta: dict[str, Any],
    storage: StorageConfig,
    upload: SmbUploadResult,
) -> None:
    meta["retry_count"] = int(meta.get("retry_count") or 0) + 1
    meta["last_retry"] = datetime.now(UTC).isoformat()
    meta["last_error"] = upload.error or "unknown SMB upload failure"
    meta["smb_path"] = storage.remote_path
    meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True))
