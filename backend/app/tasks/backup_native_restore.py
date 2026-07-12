"""Restore helpers for native backup archives."""

from __future__ import annotations

import gzip
import os
import shutil
import subprocess
import tarfile
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any

from .backup_native_archive import (
    BACKUP_TIMEOUT,
    INFRASTRUCTURE_DATABASE_DUMP_NAME,
    PROJECT_DATABASE_DUMP_NAME,
    _load_db_config,
)


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
        members = archive.getmembers()
        _, database_member_name = _validate_archive_layout(members)
        for member in members:
            is_db = _normalized_member_name(member) == database_member_name
            if db_only and not is_db:
                continue
            if files_only and is_db:
                continue
            if len(entries) < limit:
                entries.append(member.name)
            else:
                omitted += 1
    return {"status": "completed", "dry_run": True, "archive": str(path), "entries": entries, "omitted": omitted}


def _validated_member_parts(member: tarfile.TarInfo) -> tuple[str, ...]:
    """Return safe POSIX path components for a regular file/directory member."""
    name = member.name
    path = PurePosixPath(name)
    if not name or "\x00" in name or "\\" in name or path.is_absolute():
        raise RuntimeError(f"Unsafe archive path: {name}")
    if not (member.isdir() or member.isreg()):
        raise RuntimeError(f"Unsafe archive member type: {name}")

    parts = path.parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise RuntimeError(f"Unsafe archive path: {name}")
    if len(parts) == 1 and not member.isdir():
        raise RuntimeError(f"Archive file is missing its top-level directory: {name}")
    return parts


def _normalized_member_name(member: tarfile.TarInfo) -> str:
    return "/".join(_validated_member_parts(member))


def _validate_archive_layout(members: list[tarfile.TarInfo]) -> tuple[str, str | None]:
    """Validate all members and return the archive root and canonical DB member."""
    if not members:
        raise RuntimeError("Backup archive is empty")

    top_levels: set[str] = set()
    normalized_members: list[tuple[tarfile.TarInfo, str]] = []
    for member in members:
        parts = _validated_member_parts(member)
        top_levels.add(parts[0])
        normalized_members.append((member, "/".join(parts)))

    if len(top_levels) != 1:
        raise RuntimeError("Backup archive must contain exactly one top-level directory")
    top_level = next(iter(top_levels))
    canonical_database_names = (
        {f"infrastructure/{INFRASTRUCTURE_DATABASE_DUMP_NAME}"}
        if top_level == "infrastructure"
        else {f"{top_level}/{PROJECT_DATABASE_DUMP_NAME}"}
    )
    database_members = [
        (member, name)
        for member, name in normalized_members
        if name in canonical_database_names
    ]
    if len(database_members) > 1:
        raise RuntimeError("Backup archive must contain at most one database dump")

    seen_names: set[str] = set()
    for _, name in normalized_members:
        if name in seen_names:
            raise RuntimeError(f"Backup archive contains duplicate path: {name}")
        seen_names.add(name)

    regular_file_names = {
        name for member, name in normalized_members if member.isreg()
    }
    for _, name in normalized_members:
        for parent in PurePosixPath(name).parents:
            parent_name = parent.as_posix()
            if parent_name == ".":
                continue
            if parent_name in regular_file_names:
                raise RuntimeError(
                    f"Backup archive contains file/directory collision: {parent_name}"
                )

    if not database_members:
        return top_level, None

    database_member, database_member_name = database_members[0]
    if not database_member.isreg():
        raise RuntimeError("Database dump is not a regular file")
    return top_level, database_member_name


def _validate_destination_targets(
    members: list[tarfile.TarInfo],
    destination: Path,
    expected_top_level: str,
) -> None:
    """Reject existing symlink escapes before restoring any archive member."""
    root = destination.resolve()
    for member in members:
        parts = _validated_member_parts(member)
        if parts[0] != expected_top_level:
            raise RuntimeError(
                f"Unexpected archive top-level directory: {member.name}"
            )
        rel = Path(*parts[1:]) if len(parts) > 1 else Path()
        target = root / rel
        if not target.resolve().is_relative_to(root):
            raise RuntimeError(f"Unsafe archive path: {member.name}")
        if member.isdir() and target.exists() and not target.is_dir():
            raise RuntimeError(
                f"Backup archive directory conflicts with existing file: {member.name}"
            )
        if member.isreg() and target.exists() and not target.is_file():
            raise RuntimeError(
                f"Backup archive file conflicts with existing directory: {member.name}"
            )


def _safe_extract_member(
    archive: tarfile.TarFile,
    member: tarfile.TarInfo,
    destination: Path,
    expected_top_level: str,
) -> None:
    parts = _validated_member_parts(member)
    if parts[0] != expected_top_level:
        raise RuntimeError(f"Unexpected archive top-level directory: {member.name}")

    root = destination.resolve()
    rel = Path(*parts[1:]) if len(parts) > 1 else Path()
    target = (root / rel).resolve()
    if not target.is_relative_to(root):
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
    target.chmod(member.mode & 0o777)


def _restore_database_member(
    archive: tarfile.TarFile,
    member: tarfile.TarInfo,
    project_dir: Path,
    *,
    infrastructure: bool,
) -> str:
    run_env = os.environ.copy()
    if infrastructure:
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
        restored = INFRASTRUCTURE_DATABASE_DUMP_NAME
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
        restored = PROJECT_DATABASE_DUMP_NAME

    src = archive.extractfile(member)
    if src is None:
        raise RuntimeError(f"Unable to read database dump: {member.name}")
    with tempfile.TemporaryFile() as sql_file:
        with src, gzip.GzipFile(fileobj=src, mode="rb") as decompressed:
            shutil.copyfileobj(decompressed, sql_file)
        sql_file.seek(0)
        result = subprocess.run(
            command,
            stdin=sql_file,
            env=run_env,
            capture_output=True,
            timeout=BACKUP_TIMEOUT,
            check=False,
        )
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
        members = archive.getmembers()
        expected_top_level, database_member_name = _validate_archive_layout(members)
        extractable_members = [
            member
            for member in members
            if _normalized_member_name(member) != database_member_name
            and not db_only
        ]
        _validate_destination_targets(
            extractable_members,
            project_dir,
            expected_top_level,
        )
        for member in members:
            is_db = _normalized_member_name(member) == database_member_name
            if db_only and not is_db:
                continue
            if files_only and is_db:
                continue
            if is_db:
                db_restored = _restore_database_member(
                    archive,
                    member,
                    project_dir,
                    infrastructure=database_member_name
                    == f"infrastructure/{INFRASTRUCTURE_DATABASE_DUMP_NAME}",
                )
                continue
            _safe_extract_member(archive, member, project_dir, expected_top_level)
            restored += 1
    if db_only and not db_restored:
        raise RuntimeError("Archive does not contain a database dump")
    return {"status": "completed", "dry_run": False, "archive": str(path), "files_restored": restored, "db_restored": db_restored}


def archive_age_days(path: Path) -> int:
    """Return whole days since archive mtime."""
    return int((datetime.now(UTC) - datetime.fromtimestamp(path.stat().st_mtime, UTC)) / timedelta(days=1))
