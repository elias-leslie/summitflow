"""Infrastructure backup helpers for native backup tasks."""

from __future__ import annotations

import os
import shutil
import subprocess
import tarfile
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from ..logging_config import get_logger
from ..utils.shared_paths import get_repo_root
from .backup_native_archive import _run_gzip_stream, verify_archive
from .backup_native_smb import StorageConfig, _save_pending, _smb_upload, _storage_config
from .backup_native_storage import (
    copy_to_local_backend,
    local_storage_config,
    storage_backend_type,
    update_backup_index,
)

logger = get_logger(__name__)

INFRA_BACKUP_TIMEOUT = 900


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
    if storage_backend_type(run_env or {}) == "local":
        local_storage = local_storage_config(source_id, run_env or {})
        location = copy_to_local_backend(archive_path, archive_name, local_storage)
        if keep_local:
            local_dir = project_dir / "backups" / "infrastructure"
            local_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(archive_path, local_dir / archive_name)
        update_backup_index(source_id, result, "ok", location, retention)
        return {**result, "location": location}

    upload = _smb_upload(archive_path, archive_name, storage)
    if upload.ok:
        location = upload.location
        if keep_local:
            local_dir = project_dir / "backups" / "infrastructure"
            local_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(archive_path, local_dir / archive_name)
        update_backup_index(source_id, result, "ok", location, retention)
        return {**result, "location": location}
    logger.warning(
        "infra_backup_smb_upload_failed",
        archive=archive_name,
        remote_path=storage.remote_path,
        error=upload.error,
    )
    pending = _save_pending(archive_path, archive_name, source_id, storage)
    location = str(pending)
    update_backup_index(source_id, result, "pending", location, retention)
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
