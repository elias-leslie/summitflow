"""Restore helpers for native backup archives."""

from __future__ import annotations

import gzip
import os
import shutil
import subprocess
import tarfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .backup_native_archive import BACKUP_TIMEOUT, _load_db_config


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
