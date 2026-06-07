"""Storage/index helpers for native backup tasks."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .backup_native_smb import _source_remote_path


@dataclass(frozen=True)
class LocalStorageConfig:
    root_path: Path
    remote_path: str

    @property
    def location_prefix(self) -> str:
        return str(self.root_path / self.remote_path)


def storage_backend_type(env: dict[str, str]) -> str:
    return str(env.get("STORAGE_BACKEND_TYPE") or env.get("BACKUP_STORAGE_TYPE") or "smb").lower()


def local_storage_config(source_id: str, env: dict[str, str]) -> LocalStorageConfig:
    root_raw = env.get("LOCAL_BACKUP_ROOT") or env.get("BACKUP_LOCAL_ROOT") or env.get("BACKUP_ROOT")
    path_raw = env.get("LOCAL_BACKUP_PATH") or env.get("BACKUP_PATH") or "project-backups"

    if not root_raw and path_raw and Path(path_raw).expanduser().is_absolute():
        root_raw = path_raw
        path_raw = ""

    if not root_raw:
        raise RuntimeError("Local storage backend requires root_path")

    return LocalStorageConfig(
        root_path=Path(root_raw).expanduser(),
        remote_path=_source_remote_path(source_id, path_raw),
    )


def copy_to_local_backend(
    archive_path: Path,
    archive_name: str,
    storage: LocalStorageConfig,
) -> str:
    destination_dir = storage.root_path / storage.remote_path
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / archive_name
    shutil.copy2(archive_path, destination)
    return str(destination)


def backup_state_root() -> Path:
    cache = Path(os.environ.get("ST_WORKSPACES_ROOT", Path.home() / ".local" / "share" / "summitflow" / "workspaces")) / "cache"
    if cache.exists() and os.access(cache, os.W_OK):
        return cache / "backup-indexes"
    return Path.home() / ".local" / "share" / "summitflow" / "backup-indexes"


def update_backup_index(
    project_name: str,
    result: dict[str, Any],
    status: str,
    location: str,
    retention_days: int,
) -> None:
    state_dir = backup_state_root() / project_name
    state_dir.mkdir(parents=True, exist_ok=True)
    index_path = state_dir / "backup-index.json"
    payload: dict[str, Any]
    if index_path.exists():
        try:
            payload = json.loads(index_path.read_text())
        except json.JSONDecodeError:
            payload = {}
    else:
        payload = {}
    backups = payload.get("backups")
    if not isinstance(backups, list):
        backups = []
    timestamp = datetime.now(UTC).isoformat()
    backups.insert(
        0,
        {
            "name": result["archive_name"],
            "timestamp": timestamp,
            "size_bytes": result["total_bytes"],
            "db_size_bytes": result["db_bytes"],
            "status": status,
            "location": location,
            "verification": result["verification"],
        },
    )
    payload.update(
        {
            "version": 2,
            "retention_days": retention_days,
            "destination": location.rsplit("/", 1)[0] if "/" in location else location,
            "backups": backups,
            "last_updated": timestamp,
        }
    )
    index_path.write_text(json.dumps(payload, indent=2, sort_keys=True))


def apply_local_retention(local_dir: Path, keep: int = 5) -> None:
    archives = sorted(local_dir.glob("*.tar.gz"), key=lambda item: item.stat().st_mtime, reverse=True)
    for old in archives[keep:]:
        old.unlink(missing_ok=True)
