"""Native backup and restore engine used by `st backup` and backend tasks."""

from __future__ import annotations

import fnmatch
import gzip
import hashlib
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
from urllib.parse import unquote, urlsplit

from ..logging_config import get_logger
from ..utils.shared_paths import get_repo_root

logger = get_logger(__name__)

BACKUP_TIMEOUT = 600
INFRA_BACKUP_TIMEOUT = 900
DEFAULT_EXCLUDES = (
    "backend/.venv",
    "frontend/node_modules",
    "frontend/.next",
    ".git",
    ".mypy_cache",
    "backend/.mypy_cache",
    "__pycache__",
    "*.pyc",
    "*.pyo",
    "backend/.ruff_cache",
    ".ruff_cache",
    "backend/.pytest_cache",
    ".pytest_cache",
    "./backups",
    "backups",
    ".tmp",
    ".tmp-*",
    ".claude/backups",
    ".claude/plans",
    "data/artifacts",
    "data/evidence",
    "node_modules",
    "docker/compose/hatchet-config",
)


@dataclass(frozen=True)
class StorageConfig:
    host: str
    share: str
    remote_path: str
    user: str
    credentials_file: Path

    @property
    def location_prefix(self) -> str:
        return f"//{self.host}/{self.share}/{self.remote_path}"


@dataclass(frozen=True)
class SmbUploadResult:
    ok: bool
    archive_name: str
    remote_path: str
    location: str
    returncode: int | None = None
    error: str | None = None
    stdout: str = ""
    stderr: str = ""


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _project_env_name(project_name: str) -> str:
    return project_name.upper().replace("-", "_") + "_DB_URL"


def _load_db_config(project_name: str, env: dict[str, str]) -> dict[str, str]:
    env_file = _read_env_file(Path.home() / ".env.local")
    merged = {**env_file, **env}
    url = merged.get(_project_env_name(project_name), "")
    if not url:
        generic = merged.get("DATABASE_URL", "")
        url = generic if project_name in generic else ""
    default_name = project_name.replace("-", "_")
    config = {
        "name": merged.get("DB_NAME", default_name),
        "user": merged.get("DB_USER", f"{default_name}_app"),
        "password": merged.get("DB_PASSWORD", ""),
        "host": merged.get("PGHOST", "localhost"),
        "port": merged.get("PGPORT", "5432"),
    }
    if url.startswith("postgresql://"):
        parsed = urlsplit(url)
        db_name = parsed.path.lstrip("/").split("?", 1)[0]
        config.update(
            {
                "name": db_name or config["name"],
                "user": unquote(parsed.username or "") or config["user"],
                "password": unquote(parsed.password or "") or config["password"],
                "host": parsed.hostname or config["host"],
                "port": str(parsed.port or config["port"]),
            }
        )
    return config


def _storage_config(project_name: str, env: dict[str, str]) -> StorageConfig:
    env_file = _read_env_file(Path.home() / ".env.local")
    merged = {**env_file, **env}
    remote_path = _source_remote_path(project_name, merged.get("SMB_PATH"))
    return StorageConfig(
        host=merged.get("SMB_HOST", "nas.local"),
        share=merged.get("SMB_SHARE", "backups"),
        remote_path=remote_path,
        user=merged.get("SMB_USER", "backup-svc"),
        credentials_file=Path(merged.get("CREDENTIALS_FILE", str(Path.home() / ".smbcredentials"))).expanduser(),
    )


def _source_remote_path(source_id: str, configured_path: object = None) -> str:
    base = str(configured_path or "").strip().strip("/")
    if not base:
        return f"project-backups/{source_id}"
    if "{source}" in base or "{project}" in base:
        return base.replace("{source}", source_id).replace("{project}", source_id)
    if base.rsplit("/", 1)[-1] == source_id:
        return base
    return f"{base}/{source_id}"


def _backup_state_root() -> Path:
    cache = Path(os.environ.get("ST_WORKSPACES_ROOT", "/srv/workspaces")) / "cache"
    if cache.exists() and os.access(cache, os.W_OK):
        return cache / "backup-indexes"
    return Path.home() / ".local" / "share" / "summitflow" / "backup-indexes"


def _should_exclude(rel_path: str, patterns: tuple[str, ...]) -> bool:
    normalized = rel_path.removeprefix("./")
    parts = normalized.split("/")
    for pattern in patterns:
        pat = pattern.removeprefix("./").rstrip("/")
        if fnmatch.fnmatch(normalized, pat) or fnmatch.fnmatch(Path(normalized).name, pat):
            return True
        if any(fnmatch.fnmatch(part, pat) for part in parts):
            return True
        if normalized.startswith(f"{pat}/"):
            return True
    return False


def _load_excludes(project_dir: Path) -> tuple[str, ...]:
    patterns = list(DEFAULT_EXCLUDES)
    ignore_file = project_dir / ".backupignore"
    if ignore_file.exists():
        for raw_line in ignore_file.read_text(errors="ignore").splitlines():
            line = raw_line.strip()
            if line and not line.startswith("#"):
                patterns.append(line.rstrip("/"))
    return tuple(patterns)


def _run_gzip_stream(command: list[str], destination: Path, *, env: dict[str, str] | None, timeout: int) -> tuple[int, bytes]:
    proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    try:
        assert proc.stdout is not None
        with gzip.open(destination, "wb") as out:
            shutil.copyfileobj(proc.stdout, out)
        _, stderr = proc.communicate(timeout=timeout)
        return proc.returncode or 0, stderr
    except subprocess.TimeoutExpired:
        proc.kill()
        _, stderr = proc.communicate()
        raise TimeoutError from None


def _dump_database(project_name: str, destination: Path, env: dict[str, str]) -> tuple[int, bool]:
    db = _load_db_config(project_name, env)
    expects_db = bool(db["password"])
    if not db["password"]:
        return 0, expects_db
    destination.parent.mkdir(parents=True, exist_ok=True)
    run_env = {**os.environ, **env, "PGPASSWORD": db["password"]}
    command = ["pg_dump", "-U", db["user"], "-h", db["host"], "-p", db["port"], db["name"]]
    returncode, stderr = _run_gzip_stream(command, destination, env=run_env, timeout=BACKUP_TIMEOUT)
    if returncode != 0:
        detail = stderr.decode(errors="ignore").strip()
        raise RuntimeError(f"Database dump failed: {detail or returncode}")
    return destination.stat().st_size, expects_db


def _add_project_files(archive: tarfile.TarFile, project_dir: Path, project_name: str, excludes: tuple[str, ...]) -> int:
    count = 0
    for root, dirs, files in os.walk(project_dir):
        root_path = Path(root)
        rel_root = root_path.relative_to(project_dir).as_posix()
        if rel_root == ".":
            rel_root = ""
        dirs[:] = [
            dirname
            for dirname in dirs
            if not _should_exclude((Path(rel_root) / dirname).as_posix(), excludes)
        ]
        for filename in files:
            full = root_path / filename
            rel = full.relative_to(project_dir).as_posix()
            if _should_exclude(rel, excludes):
                continue
            try:
                archive.add(full, arcname=f"{project_name}/{rel}", recursive=False)
                count += 1
            except FileNotFoundError:
                continue
    return count


def _create_project_archive(project_dir: Path, project_name: str, staging: Path, env: dict[str, str]) -> dict[str, Any]:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    archive_name = f"{project_name}-{timestamp}.tar.gz"
    archive_path = staging / archive_name
    db_dump = staging / "database.sql.gz"
    db_size, expects_db = _dump_database(project_name, db_dump, env)
    if db_size == 0 and expects_db:
        raise RuntimeError(f"Database dump skipped: missing credentials for {project_name}")
    excludes = _load_excludes(project_dir)
    with tarfile.open(archive_path, "w:gz") as archive:
        files_count = _add_project_files(archive, project_dir, project_name, excludes)
        if db_dump.exists():
            archive.add(db_dump, arcname=f"{project_name}/database.sql.gz", recursive=False)
            files_count += 1
    verification = verify_archive(archive_path, db_dump_name="database.sql.gz", expects_db=expects_db)
    total_size = archive_path.stat().st_size
    return {
        "archive_name": archive_name,
        "archive_path": archive_path,
        "total_bytes": total_size,
        "db_bytes": db_size,
        "files_bytes": max(total_size - db_size, 0),
        "total_files": files_count,
        "verification": verification,
    }


def verify_archive(path: Path, *, db_dump_name: str, expects_db: bool) -> dict[str, Any]:
    errors: list[str] = []
    tree: dict[str, dict[str, int]] = {}
    names: list[str] = []
    try:
        with tarfile.open(path, "r:gz") as archive:
            names = [member.name for member in archive.getmembers() if member.isfile()]
    except (tarfile.TarError, OSError) as exc:
        return {
            "verified": False,
            "verified_at": datetime.now(UTC).isoformat(),
            "errors": [f"Archive integrity check failed: {exc}"],
            "tree": {},
            "total_files": 0,
            "checksum": "",
            "has_db": False,
            "expects_db": expects_db,
        }
    for name in names:
        stripped = name.split("/", 1)[1] if "/" in name else name
        top = stripped.split("/", 1)[0]
        tree.setdefault(top, {"count": 0})["count"] += 1
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    has_db = any(name.endswith(db_dump_name) for name in names)
    if expects_db and not has_db:
        errors.append(f"Critical: {db_dump_name} missing")
    return {
        "verified": not errors,
        "verified_at": datetime.now(UTC).isoformat(),
        "errors": errors,
        "tree": tree,
        "total_files": len(names),
        "checksum": f"sha256:{digest}",
        "has_db": has_db,
        "expects_db": expects_db,
    }


def _smb_probe_dir(remote_path: str) -> str:
    parent = remote_path.rsplit("/", 1)[0] if "/" in remote_path else "."
    return parent or "."


def _smb_available(storage: StorageConfig) -> bool:
    if not storage.credentials_file.exists() or not shutil.which("smbclient"):
        return False
    probe_dir = _smb_probe_dir(storage.remote_path)
    result = subprocess.run(
        ["smbclient", f"//{storage.host}/{storage.share}", "-A", str(storage.credentials_file), "-c", f"cd {probe_dir}; ls"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    return result.returncode == 0


def _smb_output(stdout: str, stderr: str, limit: int = 1200) -> str:
    detail = "\n".join(part.strip() for part in (stdout, stderr) if part.strip())
    return detail[-limit:]


def _smb_command(storage: StorageConfig, command: str, *, timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["smbclient", f"//{storage.host}/{storage.share}", "-A", str(storage.credentials_file), "-c", command],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _smb_cd_ok(storage: StorageConfig, remote_path: str) -> bool:
    result = _smb_command(storage, f"cd {remote_path}; ls", timeout=30)
    return result.returncode == 0


def _ensure_smb_dir(storage: StorageConfig) -> SmbUploadResult:
    if _smb_cd_ok(storage, storage.remote_path):
        return SmbUploadResult(
            ok=True,
            archive_name="",
            remote_path=storage.remote_path,
            location=storage.location_prefix,
        )

    parts = [part for part in storage.remote_path.split("/") if part]
    current = ""
    last_result: subprocess.CompletedProcess[str] | None = None
    for part in parts:
        current = f"{current}/{part}" if current else part
        last_result = _smb_command(storage, f"mkdir {current}", timeout=30)

    check = _smb_command(storage, f"cd {storage.remote_path}; ls", timeout=30)
    if check.returncode == 0:
        return SmbUploadResult(
            ok=True,
            archive_name="",
            remote_path=storage.remote_path,
            location=storage.location_prefix,
        )

    detail_source = check if check.stdout or check.stderr else last_result
    stdout = detail_source.stdout if detail_source else ""
    stderr = detail_source.stderr if detail_source else ""
    return SmbUploadResult(
        ok=False,
        archive_name="",
        remote_path=storage.remote_path,
        location=storage.location_prefix,
        returncode=check.returncode,
        error=f"remote directory unavailable: {_smb_output(stdout, stderr)}",
        stdout=stdout,
        stderr=stderr,
    )


def _smb_upload(path: Path, archive_name: str, storage: StorageConfig) -> SmbUploadResult:
    if not storage.credentials_file.exists():
        return SmbUploadResult(
            ok=False,
            archive_name=archive_name,
            remote_path=storage.remote_path,
            location=f"{storage.location_prefix}/{archive_name}",
            error=f"credentials file missing: {storage.credentials_file}",
        )
    if not shutil.which("smbclient"):
        return SmbUploadResult(
            ok=False,
            archive_name=archive_name,
            remote_path=storage.remote_path,
            location=f"{storage.location_prefix}/{archive_name}",
            error="smbclient not found",
        )

    directory = _ensure_smb_dir(storage)
    if not directory.ok:
        return SmbUploadResult(
            ok=False,
            archive_name=archive_name,
            remote_path=storage.remote_path,
            location=f"{storage.location_prefix}/{archive_name}",
            returncode=directory.returncode,
            error=directory.error,
            stdout=directory.stdout,
            stderr=directory.stderr,
        )

    command = f'cd {storage.remote_path}; put "{path}" "{archive_name}"; ls "{archive_name}"'
    result = _smb_command(storage, command, timeout=300)
    output = result.stdout + result.stderr
    ok = result.returncode == 0 and archive_name in output
    error = None if ok else f"upload failed rc={result.returncode}: {_smb_output(result.stdout, result.stderr)}"
    return SmbUploadResult(
        ok=ok,
        archive_name=archive_name,
        remote_path=storage.remote_path,
        location=f"{storage.location_prefix}/{archive_name}",
        returncode=result.returncode,
        error=error,
        stdout=result.stdout,
        stderr=result.stderr,
    )


def _save_pending(path: Path, archive_name: str, project_name: str, storage: StorageConfig) -> Path:
    pending_dir = Path.home() / ".local" / "share" / "backup-pending"
    pending_dir.mkdir(parents=True, exist_ok=True)
    pending = pending_dir / archive_name
    shutil.copy2(path, pending)
    meta = {
        "project": project_name,
        "archive": archive_name,
        "created_at": datetime.now(UTC).isoformat(),
        "smb_host": storage.host,
        "smb_share": storage.share,
        "smb_path": storage.remote_path,
        "retry_count": 0,
    }
    pending.with_suffix(pending.suffix + ".meta").write_text(json.dumps(meta, indent=2, sort_keys=True))
    return pending


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
    storage = _storage_config(project_name, run_env)
    retention = retention_days or 14
    with tempfile.TemporaryDirectory(prefix=f"{project_name}-backup-") as temp_dir:
        result = _create_project_archive(project_path, project_name, Path(temp_dir), run_env)
        archive_name = str(result["archive_name"])
        archive_path = Path(result["archive_path"])
        if local_only:
            final_dir = project_path / "backups"
            final_dir.mkdir(parents=True, exist_ok=True)
            final_path = final_dir / archive_name
            shutil.copy2(archive_path, final_path)
            location = str(final_path)
            _update_backup_index(source_id, result, "ok", location, retention)
            return {**result, "archive_path": final_path, "location": location}
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
    storage = _storage_config(source_id, {**run_env, "SMB_PATH": "project-backups/infrastructure"})
    retention = retention_days or 14
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    archive_name = f"infrastructure-{timestamp}.tar.gz"
    with tempfile.TemporaryDirectory(prefix="infrastructure-backup-") as temp_dir:
        staging = Path(temp_dir)
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


def _storage_from_pending_meta(meta: dict[str, Any], archive: Path) -> StorageConfig:
    source_id = str(meta.get("project") or archive.stem.rsplit("-", 2)[0] or archive.stem)
    remote_path = _source_remote_path(source_id, meta.get("smb_path"))
    return StorageConfig(
        host=str(meta.get("smb_host") or "nas.local"),
        share=str(meta.get("smb_share") or "backups"),
        remote_path=remote_path,
        user=os.environ.get("SMB_USER", "backup-svc"),
        credentials_file=Path.home() / ".smbcredentials",
    )


def drain_pending_archives(*, dry_run: bool = False) -> dict[str, Any]:
    """Upload pending archives to their recorded SMB target."""
    pending_dir = Path.home() / ".local" / "share" / "backup-pending"
    archives = sorted(pending_dir.glob("*.tar.gz")) if pending_dir.exists() else []
    if not archives:
        return {"status": "success", "message": "No pending uploads to drain", "uploaded": 0, "remaining": 0}
    if dry_run:
        return {
            "status": "dry_run",
            "message": f"{len(archives)} backup(s) pending upload",
            "pending_before": len(archives),
            "backups": [{"name": path.name, "location": str(path), "size_bytes": path.stat().st_size} for path in archives],
        }
    uploaded = 0
    failures: list[dict[str, Any]] = []
    uploaded_archives: dict[str, str] = {}
    for archive in archives:
        meta_path = archive.with_suffix(archive.suffix + ".meta")
        if not meta_path.exists():
            failures.append(
                {
                    "name": archive.name,
                    "location": str(archive),
                    "error": "missing metadata file",
                }
            )
            logger.warning("backup_pending_missing_metadata", archive=archive.name, path=str(archive))
            continue
        try:
            meta = json.loads(meta_path.read_text())
        except json.JSONDecodeError as exc:
            failures.append(
                {
                    "name": archive.name,
                    "location": str(archive),
                    "error": f"invalid metadata JSON: {exc}",
                }
            )
            logger.warning("backup_pending_invalid_metadata", archive=archive.name, error=str(exc))
            continue
        storage = _storage_from_pending_meta(meta, archive)
        upload = _smb_upload(archive, archive.name, storage)
        if upload.ok:
            archive.unlink(missing_ok=True)
            meta_path.unlink(missing_ok=True)
            uploaded += 1
            uploaded_archives[archive.name] = upload.location
        else:
            meta["retry_count"] = int(meta.get("retry_count") or 0) + 1
            meta["last_retry"] = datetime.now(UTC).isoformat()
            meta["last_error"] = upload.error or "unknown SMB upload failure"
            meta["smb_path"] = storage.remote_path
            meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True))
            failures.append(
                {
                    "name": archive.name,
                    "location": str(archive),
                    "remote_path": storage.remote_path,
                    "returncode": upload.returncode,
                    "error": upload.error,
                }
            )
            logger.warning(
                "backup_pending_upload_failed",
                archive=archive.name,
                remote_path=storage.remote_path,
                returncode=upload.returncode,
                error=upload.error,
            )
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
