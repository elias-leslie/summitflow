"""Native backup and restore engine used by `st backup` and backend tasks."""

from __future__ import annotations

import gzip
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from ..logging_config import get_logger
from ..utils.shared_paths import get_repo_root
from .backup_native_archive import (
    BACKUP_TIMEOUT,
    _create_project_archive,
    _load_db_config,
    _run_gzip_stream,
    verify_archive,
)
from .backup_native_pending import drain_pending_archives_from_dir
from .backup_native_smb import (
    SmbUploadResult,
    StorageConfig,
    _save_pending,
    _smb_upload,
    _source_remote_path,
    _storage_config,
)

logger = get_logger(__name__)

INFRA_BACKUP_TIMEOUT = 900


@dataclass(frozen=True)
class LocalStorageConfig:
    root_path: Path
    remote_path: str

    @property
    def location_prefix(self) -> str:
        return str(self.root_path / self.remote_path)


def _storage_backend_type(env: dict[str, str]) -> str:
    return str(env.get("STORAGE_BACKEND_TYPE") or env.get("BACKUP_STORAGE_TYPE") or "smb").lower()


def _local_storage_config(source_id: str, env: dict[str, str]) -> LocalStorageConfig:
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


def _copy_to_local_backend(
    archive_path: Path,
    archive_name: str,
    storage: LocalStorageConfig,
) -> str:
    destination_dir = storage.root_path / storage.remote_path
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / archive_name
    shutil.copy2(archive_path, destination)
    return str(destination)


def _backup_state_root() -> Path:
    cache = Path(os.environ.get("ST_WORKSPACES_ROOT", "/srv/workspaces")) / "cache"
    if cache.exists() and os.access(cache, os.W_OK):
        return cache / "backup-indexes"
    return Path.home() / ".local" / "share" / "summitflow" / "backup-indexes"


def _update_backup_index(project_name: str, result: dict[str, Any], status: str, location: str, retention_days: int) -> None:
    state_dir = _backup_state_root() / project_name
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


def _apply_local_retention(local_dir: Path, keep: int = 5) -> None:
    archives = sorted(local_dir.glob("*.tar.gz"), key=lambda item: item.stat().st_mtime, reverse=True)
    for old in archives[keep:]:
        old.unlink(missing_ok=True)


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
    _update_backup_index(source_id, result, "ok", location, retention)
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
    if _storage_backend_type(run_env) == "local":
        local_storage = _local_storage_config(source_id, run_env)
        location = _copy_to_local_backend(archive_path, archive_name, local_storage)
        if keep_local:
            local_dir = project_path / "backups"
            local_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(archive_path, local_dir / archive_name)
            _apply_local_retention(local_dir)
        _update_backup_index(source_id, result, "ok", location, retention)
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
                _apply_local_retention(local_dir)
            _update_backup_index(source_id, result, "ok", location, retention)
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
    _update_backup_index(source_id, result, "pending", location, retention)
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


def _find_compose_container(service: str) -> str | None:
    if not Path("/var/run/docker.sock").exists():
        return None
    commands = [
        ["docker", "compose", "-p", "summitflow-stack", "ps", "--format", "{{.Name}}", service],
        ["docker", "ps", "--filter", f"label=com.docker.compose.service={service}", "--format", "{{.Names}}"],
    ]
    for command in commands:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip().splitlines()[0]
    return None


def _dump_infra_database(destination: Path) -> int:
    pg_user = os.environ.get("PGUSER", "admin")
    pg_host = os.environ.get("PGHOST", "localhost")
    pg_container = os.environ.get("POSTGRES_CONTAINER") or _find_compose_container("postgres")
    if pg_container:
        command = ["docker", "exec", pg_container, "pg_dumpall", "-U", pg_user]
        returncode, stderr = _run_gzip_stream(command, destination, env=None, timeout=INFRA_BACKUP_TIMEOUT)
    else:
        env = {**os.environ, "PGPASSWORD": os.environ.get("PGPASSWORD", "")}
        command = ["pg_dumpall", "-U", pg_user, "-h", pg_host]
        returncode, stderr = _run_gzip_stream(command, destination, env=env, timeout=INFRA_BACKUP_TIMEOUT)
    if returncode != 0:
        detail = stderr.decode(errors="ignore").strip()
        raise RuntimeError(f"pg_dumpall failed: {detail or returncode}")
    return destination.stat().st_size


def _copy_if_exists(src: Path, dest: Path) -> int:
    if not src.exists():
        return 0
    dest.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        shutil.copytree(src, dest, dirs_exist_ok=True)
    else:
        shutil.copy2(src, dest)
    return 1


def _collect_redis_dump(destination: Path) -> None:
    redis_cli = shutil.which("redis-cli")
    if redis_cli:
        result = subprocess.run([redis_cli, "-h", os.environ.get("REDIS_HOST", "localhost"), "-p", os.environ.get("REDIS_PORT", "6379"), "--rdb", str(destination)], check=False)
        if result.returncode == 0 and destination.exists() and destination.stat().st_size > 0:
            return
    container = _find_compose_container("redis")
    if not container:
        return
    subprocess.run(["docker", "exec", container, "redis-cli", "BGSAVE"], check=False)
    time.sleep(2)
    with destination.open("wb") as out:
        subprocess.run(["docker", "exec", container, "cat", "/data/dump.rdb"], stdout=out, check=False)


def _build_infra_archive(project_dir: Path, staging: Path, archive_name: str) -> tuple[Path, int, dict[str, Any]]:
    configs = staging / "configs"
    configs.mkdir(parents=True, exist_ok=True)
    db_dump = staging / "pgdumpall.sql.gz"
    db_size = _dump_infra_database(db_dump)
    _copy_if_exists(Path.home() / ".env.local", configs / "env.local")
    _copy_if_exists(project_dir / "docker" / "compose" / ".env", configs / "compose-env")
    _copy_if_exists(Path.home() / ".smbcredentials", configs / "smbcredentials")
    _copy_if_exists(project_dir / "docker" / "compose" / "hatchet-config", configs / "hatchet-config")
    _collect_redis_dump(configs / "redis-dump.rdb")
    archive_path = staging / archive_name
    with tarfile.open(archive_path, "w:gz") as archive:
        archive.add(db_dump, arcname="infrastructure/pgdumpall.sql.gz", recursive=False)
        archive.add(configs, arcname="infrastructure/configs", recursive=True)
    verification = verify_archive(archive_path, db_dump_name="pgdumpall.sql.gz", expects_db=True)
    result = {
        "archive_name": archive_name,
        "archive_path": archive_path,
        "total_bytes": archive_path.stat().st_size,
        "db_bytes": db_size,
        "files_bytes": max(archive_path.stat().st_size - db_size, 0),
        "verification": verification,
    }
    return archive_path, db_size, result


def _finish_infra_backup(
    project_dir: Path,
    source_id: str,
    result: dict[str, Any],
    archive_path: Path,
    storage: StorageConfig,
    keep_local: bool,
    retention: int,
    run_env: dict[str, str] | None = None,
) -> dict[str, Any]:
    archive_name = str(result["archive_name"])
    if _storage_backend_type(run_env or {}) == "local":
        local_storage = _local_storage_config(source_id, run_env or {})
        location = _copy_to_local_backend(archive_path, archive_name, local_storage)
        if keep_local:
            local_dir = project_dir / "backups" / "infrastructure"
            local_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(archive_path, local_dir / archive_name)
        _update_backup_index(source_id, result, "ok", location, retention)
        return {**result, "location": location}

    upload = _smb_upload(archive_path, archive_name, storage)
    if upload.ok:
        location = upload.location
        if keep_local:
            local_dir = project_dir / "backups" / "infrastructure"
            local_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(archive_path, local_dir / archive_name)
        _update_backup_index(source_id, result, "ok", location, retention)
        return {**result, "location": location}
    logger.warning(
        "infra_backup_smb_upload_failed",
        archive=archive_name,
        remote_path=storage.remote_path,
        error=upload.error,
    )
    pending = _save_pending(archive_path, archive_name, source_id, storage)
    location = str(pending)
    _update_backup_index(source_id, result, "pending", location, retention)
    return {**result, "location": location, "pending_path": location, "upload_error": upload.error}


def run_infra_backup(
    *,
    env: dict[str, str] | None = None,
    keep_local: bool = False,
    retention_days: int | None = None,
) -> dict[str, Any]:
    """Create an infrastructure backup archive."""
    source_id = "infrastructure"
    project_dir = get_repo_root()
    run_env = dict(env or {})
    storage_env = {**run_env, "SMB_PATH": run_env.get("SMB_PATH", "project-backups/infrastructure")}
    storage = _storage_config(source_id, storage_env)
    retention = retention_days or 14
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    archive_name = f"infrastructure-{timestamp}.tar.gz"
    with tempfile.TemporaryDirectory(prefix="infrastructure-backup-") as temp_dir:
        staging = Path(temp_dir)
        archive_path, _, result = _build_infra_archive(project_dir, staging, archive_name)
        return _finish_infra_backup(
            project_dir,
            source_id,
            result,
            archive_path,
            storage,
            keep_local,
            retention,
            run_env=run_env,
        )


def drain_pending_archives(*, dry_run: bool = False) -> dict[str, Any]:
    """Upload pending archives to their recorded SMB target."""
    pending_dir = Path.home() / ".local" / "share" / "backup-pending"
    return drain_pending_archives_from_dir(pending_dir, dry_run=dry_run, uploader=_smb_upload)


def locate_archive(project_dir: Path, backup: dict[str, Any] | None = None, backup_file: str | None = None) -> Path | None:
    """Locate a local or pending archive for restore/preview."""
    if backup_file:
        path = Path(backup_file).expanduser()
        return path if path.exists() else None
    location = str((backup or {}).get("location") or "")
    name = str((backup or {}).get("name") or "")
    if location and not location.startswith("//"):
        path = Path(location)
        if path.exists():
            return path
    for directory in (project_dir / "backups", Path.home() / ".local" / "share" / "backup-pending"):
        path = directory / name if name else None
        if path and path.exists():
            return path
    return None


def preview_restore_archive(path: Path, *, db_only: bool = False, files_only: bool = False, limit: int = 50) -> dict[str, Any]:
    """Return archive restore preview metadata."""
    entries: list[str] = []
    omitted = 0
    with tarfile.open(path, "r:gz") as archive:
        for member in archive.getmembers():
            is_db = member.name.endswith(("database.sql.gz", "pgdumpall.sql.gz"))
            if db_only and not is_db:
                continue
            if files_only and is_db:
                continue
            if len(entries) < limit:
                entries.append(member.name)
            else:
                omitted += 1
    return {"status": "completed", "dry_run": True, "archive": str(path), "entries": entries, "omitted": omitted}


def _safe_extract_member(archive: tarfile.TarFile, member: tarfile.TarInfo, destination: Path) -> None:
    parts = Path(member.name).parts
    rel = Path(*parts[1:]) if len(parts) > 1 else Path(parts[0])
    target = (destination / rel).resolve()
    if not str(target).startswith(str(destination.resolve())):
        raise RuntimeError(f"Unsafe archive path: {member.name}")
    if member.isdir():
        target.mkdir(parents=True, exist_ok=True)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    src = archive.extractfile(member)
    if src is None:
        return
    with src, target.open("wb") as out:
        shutil.copyfileobj(src, out)


def _restore_database_member(archive: tarfile.TarFile, member: tarfile.TarInfo, project_dir: Path) -> str:
    src = archive.extractfile(member)
    if src is None:
        raise RuntimeError(f"Unable to read database dump: {member.name}")
    with src:
        sql_bytes = gzip.decompress(src.read())
    run_env = os.environ.copy()
    if member.name.endswith("pgdumpall.sql.gz"):
        command = [
            "psql",
            "-U",
            run_env.get("PGUSER", "admin"),
            "-h",
            run_env.get("PGHOST", "localhost"),
            "-p",
            run_env.get("PGPORT", "5432"),
            "-d",
            "postgres",
            "-v",
            "ON_ERROR_STOP=1",
        ]
        restored = "pgdumpall.sql.gz"
    else:
        db = _load_db_config(project_dir.name, run_env)
        if db["password"]:
            run_env["PGPASSWORD"] = db["password"]
        command = [
            "psql",
            "-U",
            db["user"],
            "-h",
            db["host"],
            "-p",
            db["port"],
            "-d",
            db["name"],
            "-v",
            "ON_ERROR_STOP=1",
        ]
        restored = "database.sql.gz"
    result = subprocess.run(command, input=sql_bytes, env=run_env, capture_output=True, timeout=BACKUP_TIMEOUT, check=False)
    if result.returncode != 0:
        detail = result.stderr.decode(errors="ignore").strip()
        raise RuntimeError(f"Database restore failed: {detail or result.returncode}")
    return restored


def restore_archive(path: Path, project_dir: Path, *, dry_run: bool, db_only: bool = False, files_only: bool = False) -> dict[str, Any]:
    """Restore a local archive safely, or preview when dry_run is true."""
    if dry_run:
        return preview_restore_archive(path, db_only=db_only, files_only=files_only)
    restored = 0
    db_restored: str | None = None
    with tarfile.open(path, "r:gz") as archive:
        for member in archive.getmembers():
            is_db = member.name.endswith(("database.sql.gz", "pgdumpall.sql.gz"))
            if db_only and not is_db:
                continue
            if files_only and is_db:
                continue
            if is_db:
                db_restored = _restore_database_member(archive, member, project_dir)
                continue
            _safe_extract_member(archive, member, project_dir)
            restored += 1
    if db_only and not db_restored:
        raise RuntimeError("Archive does not contain a database dump")
    return {"status": "completed", "dry_run": False, "archive": str(path), "files_restored": restored, "db_restored": db_restored}


def archive_age_days(path: Path) -> int:
    """Return whole days since archive mtime."""
    return int((datetime.now(UTC) - datetime.fromtimestamp(path.stat().st_mtime, UTC)) / timedelta(days=1))
