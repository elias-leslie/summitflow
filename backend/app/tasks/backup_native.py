"""Native backup and restore engine used by `st backup` and backend tasks."""

from __future__ import annotations

import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from ..logging_config import get_logger
from .backup_native_archive import (
    BACKUP_TIMEOUT,
    _create_project_archive,
)
from .backup_native_infra import INFRA_BACKUP_TIMEOUT, run_infra_backup
from .backup_native_pending import drain_pending_archives_from_dir
from .backup_native_restore import (
    archive_age_days,
    locate_archive,
    preview_restore_archive,
    restore_archive,
)
from .backup_native_smb import (
    SmbUploadResult,
    StorageConfig,
    _save_pending,
    _smb_upload,
    _storage_config,
)
from .backup_native_storage import (
    apply_local_retention,
    copy_to_local_backend,
    local_storage_config,
    storage_backend_type,
    update_backup_index,
)

logger = get_logger(__name__)

__all__ = [
    "BACKUP_TIMEOUT",
    "INFRA_BACKUP_TIMEOUT",
    "SmbUploadResult",
    "archive_age_days",
    "drain_pending_archives",
    "locate_archive",
    "preview_restore_archive",
    "restore_archive",
    "run_infra_backup",
    "run_project_backup",
]


def _store_local_project_archive(
    project_path: Path,
    source_id: str,
    result: dict[str, Any],
    archive_path: Path,
    archive_name: str,
    retention: int,
) -> dict[str, Any]:
    final_dir = project_path / "backups"
    final_dir.mkdir(parents=True, exist_ok=True)
    final_path = final_dir / archive_name
    shutil.copy2(archive_path, final_path)
    location = str(final_path)
    update_backup_index(source_id, result, "ok", location, retention)
    return {**result, "archive_path": final_path, "location": location}


def _upload_project_archive(
    project_path: Path,
    source_id: str,
    result: dict[str, Any],
    archive_path: Path,
    storage: StorageConfig,
    run_env: dict[str, str],
    keep_local: bool,
    retention: int,
) -> dict[str, Any]:
    archive_name = str(result["archive_name"])
    if storage_backend_type(run_env) == "local":
        local_storage = local_storage_config(source_id, run_env)
        location = copy_to_local_backend(archive_path, archive_name, local_storage)
        if keep_local:
            local_dir = project_path / "backups"
            local_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(archive_path, local_dir / archive_name)
            apply_local_retention(local_dir)
        update_backup_index(source_id, result, "ok", location, retention)
        return {**result, "location": location}

    max_retries = int(run_env.get("SMB_MAX_RETRIES", "5"))
    last_upload: SmbUploadResult | None = None
    for attempt in range(max_retries):
        last_upload = _smb_upload(archive_path, archive_name, storage)
        if last_upload.ok:
            location = last_upload.location
            if keep_local:
                local_dir = project_path / "backups"
                local_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(archive_path, local_dir / archive_name)
                apply_local_retention(local_dir)
            update_backup_index(source_id, result, "ok", location, retention)
            return {**result, "location": location}
        logger.warning(
            "backup_smb_upload_failed",
            archive=archive_name,
            source_id=source_id,
            attempt=attempt + 1,
            attempts=max_retries,
            remote_path=storage.remote_path,
            error=last_upload.error,
        )
        if attempt < max_retries - 1:
            time.sleep(min(60, 5 * (2**attempt)))
    pending = _save_pending(archive_path, archive_name, source_id, storage)
    location = str(pending)
    update_backup_index(source_id, result, "pending", location, retention)
    return {
        **result,
        "location": location,
        "pending_path": location,
        "upload_error": last_upload.error if last_upload else "SMB upload not attempted",
    }


def run_project_backup(
    *,
    project_dir: str,
    source_id: str,
    env: dict[str, str] | None = None,
    keep_local: bool = False,
    local_only: bool = False,
    retention_days: int | None = None,
) -> dict[str, Any]:
    """Create a project/source archive and return parsed backup metadata."""
    project_path = Path(project_dir)
    project_name = project_path.name
    run_env = dict(env or {})
    retention = retention_days or 14
    with tempfile.TemporaryDirectory(prefix=f"{project_name}-backup-") as temp_dir:
        result = _create_project_archive(project_path, project_name, Path(temp_dir), run_env)
        archive_name = str(result["archive_name"])
        archive_path = Path(result["archive_path"])
        if local_only:
            return _store_local_project_archive(project_path, source_id, result, archive_path, archive_name, retention)
        storage = _storage_config(project_name, run_env)
        return _upload_project_archive(project_path, source_id, result, archive_path, storage, run_env, keep_local, retention)


def drain_pending_archives(*, dry_run: bool = False) -> dict[str, Any]:
    """Upload pending archives to their recorded SMB target."""
    pending_dir = Path.home() / ".local" / "share" / "backup-pending"
    return drain_pending_archives_from_dir(pending_dir, dry_run=dry_run, uploader=_smb_upload)
