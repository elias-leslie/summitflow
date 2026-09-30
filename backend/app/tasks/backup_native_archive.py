from __future__ import annotations

import fnmatch
import gzip
import hashlib
import io
import json
import os
import stat
import tarfile
import time
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO
from urllib.parse import unquote, urlsplit

from .backup_activity import BackupCancelled, backup_phase, check_backup_cancelled, run_bulk_process
from .backup_codex_policy import CODEX_CAPTURE_PROFILE, is_codex_recovery_input
from .backup_native_recovery import (
    RECOVERY_DIR_NAME,
    RECOVERY_MANIFEST_NAME,
    _safe_relative_symlink,
    build_consistent_snapshot,
)

BACKUP_TIMEOUT = 600
PROJECT_DATABASE_DUMP_NAME = "database.sql.gz"
INFRASTRUCTURE_DATABASE_DUMP_NAME = "pgdumpall.sql.gz"
PROJECT_DATABASE_PAYLOAD_NAME = "database.sql"
INFRASTRUCTURE_DATABASE_PAYLOAD_NAME = "pgdumpall.sql"
DEFAULT_EXCLUDES = (
    ".venv",
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
    # Only generated output at the project root, never source modules named
    # backups (for example backend/app/storage/backups or UI routes).
    "./backups",
    ".tmp",
    ".tmp-*",
    ".claude/backups",
    "node_modules",
    "docker/compose/hatchet-config",
)


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


def _should_exclude(rel_path: str, patterns: tuple[str, ...]) -> bool:
    normalized = rel_path.removeprefix("./")
    parts = normalized.split("/")
    for pattern in patterns:
        pat = pattern.removeprefix("./").rstrip("/")
        if pattern.startswith("./"):
            if fnmatch.fnmatch(normalized, pat) or normalized.startswith(f"{pat}/"):
                return True
            continue
        if fnmatch.fnmatch(normalized, pat) or fnmatch.fnmatch(Path(normalized).name, pat):
            return True
        if any(fnmatch.fnmatch(part, pat) for part in parts):
            return True
        if normalized.startswith(f"{pat}/"):
            return True
    return False


def _load_excludes(project_dir: Path) -> tuple[str, ...]:
    patterns = list(DEFAULT_EXCLUDES)
    if project_dir.is_file():
        return tuple(patterns)
    ignore_file = project_dir / ".backupignore"
    if ignore_file.exists():
        for raw_line in ignore_file.read_text(errors="ignore").splitlines():
            line = raw_line.strip()
            if line and not line.startswith("#"):
                if line.startswith("!"):
                    # Explicitly opt a durable project directory back in. Only
                    # remove an exact inherited pattern; do not reinterpret
                    # unrelated exclusions or descend into excluded parents.
                    included = line[1:].removeprefix("./").rstrip("/")
                    patterns = [p for p in patterns if p.removeprefix("./").rstrip("/") != included]
                else:
                    patterns.append(line.rstrip("/"))
    return tuple(patterns)


def _run_gzip_stream(
    command: list[str],
    destination: Path,
    *,
    env: dict[str, str] | None,
    timeout: float,
) -> tuple[int, bytes]:
    """Stream a dump without a total-duration kill or stderr pipe deadlock."""
    def compress(source: BinaryIO) -> None:
        with gzip.open(destination, "wb") as out:
            while True:
                check_backup_cancelled()
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)

    result = run_bulk_process(
        command, env=env, phase="database_dump", object_name=destination.name,
        attention_after=timeout, stdout_sink=compress, text=False,
    )
    return result.returncode, result.stderr


def _run_plain_stream(
    command: list[str], destination: Path, *, env: dict[str, str] | None, timeout: float,
) -> tuple[int, bytes]:
    """Capture bounded dump output before any archival compression."""
    def copy(source: BinaryIO) -> None:
        with destination.open("wb") as out:
            while True:
                check_backup_cancelled()
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)

    result = run_bulk_process(
        command, env=env, phase="database_dump", object_name=destination.name,
        attention_after=timeout, stdout_sink=copy, text=False,
    )
    return result.returncode, result.stderr


def _gzip_payload_file(source: Path, destination: Path) -> int:
    with source.open("rb") as plain, destination.open("wb") as raw, gzip.GzipFile(
        filename="", mode="wb", fileobj=raw, mtime=0,
    ) as compressed:
        while True:
            check_backup_cancelled()
            chunk = plain.read(1024 * 1024)
            if not chunk:
                break
            compressed.write(chunk)
    return destination.stat().st_size


class _CheckedReader(io.BufferedReader):
    """Keep long tar/compression reads responsive without changing their bytes."""

    def read(self, size: int | None = -1) -> bytes:
        check_backup_cancelled()
        return super().read(size)


def _add_checked_file(
    archive: tarfile.TarFile, source: Path, arcname: str, *, regular_only: bool = False,
) -> None:
    check_backup_cancelled()
    member_filter = _regular_file_filter if regular_only else _recoverable_file_filter
    member = member_filter(archive.gettarinfo(str(source), arcname))
    if member is None:
        return
    if member.isreg():
        with source.open("rb") as source_file, _CheckedReader(source_file) as checked:
            archive.addfile(member, checked)
    else:
        archive.addfile(member)


def _dump_database(project_name: str, destination: Path, env: dict[str, str]) -> tuple[int, bool]:
    db = _load_db_config(project_name, env)
    expects_db = bool(db["password"])
    if not db["password"]:
        return 0, expects_db
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Prefer PGUSER/PGPASSWORD (typically superuser) to avoid connection-slot
    # exhaustion for non-superuser roles.
    run_env = {**os.environ, **env}
    user = run_env.get("PGUSER", db["user"])
    password = run_env.get("PGPASSWORD", db["password"])
    # A complete backup of forced-RLS tables needs the existing backup/admin
    # identity. Never weaken the application's role or its row policies.
    admin_url = run_env.get("POSTGRES_ADMIN_URL") or _read_env_file(Path.home() / ".env.local").get("POSTGRES_ADMIN_URL")
    if admin_url and not (run_env.get("PGUSER") and run_env.get("PGPASSWORD")):
        admin = urlsplit(admin_url)
        aliases = {"localhost": "127.0.0.1", "::1": "127.0.0.1"}
        if (aliases.get(admin.hostname or "", admin.hostname) != aliases.get(db["host"], db["host"])
                or (admin.port or 5432) != int(db["port"])):
            raise RuntimeError("Backup administrator and project database endpoints differ")
        if admin.username and admin.password:
            user, password = unquote(admin.username), unquote(admin.password)
    run_env["PGPASSWORD"] = password
    command = ["pg_dump", "-U", user, "-h", db["host"], "-p", db["port"], db["name"]]
    stream = _run_gzip_stream if destination.suffix == ".gz" else _run_plain_stream
    returncode, stderr = stream(command, destination, env=run_env, timeout=BACKUP_TIMEOUT)
    if returncode != 0:
        detail = stderr.decode(errors="ignore").strip()
        raise RuntimeError(f"Database dump failed: {detail or returncode}")
    return destination.stat().st_size, expects_db


def _add_project_files(
    archive: tarfile.TarFile,
    project_dir: Path,
    project_name: str,
    excludes: tuple[str, ...],
) -> int:
    count = 0
    def walk_error(error: OSError) -> None:
        raise error

    for root, dirs, files in os.walk(project_dir, onerror=walk_error):
        check_backup_cancelled()
        root_path = Path(root)
        rel_root = root_path.relative_to(project_dir).as_posix()
        rel_root = "" if rel_root == "." else rel_root
        retained_dirs: list[str] = []
        for dirname in dirs:
            rel = (Path(rel_root) / dirname).as_posix()
            if _should_exclude(rel, excludes):
                continue
            if (root_path / dirname).is_symlink():
                files.append(dirname)
            else:
                retained_dirs.append(dirname)
        dirs[:] = retained_dirs
        count += _add_files_from_dir(archive, root_path, project_dir, project_name, excludes, files)
    return count


def _add_files_from_dir(
    archive: tarfile.TarFile,
    root_path: Path,
    project_dir: Path,
    project_name: str,
    excludes: tuple[str, ...],
    files: list[str],
) -> int:
    count = 0
    for filename in files:
        check_backup_cancelled()
        full = root_path / filename
        rel = full.relative_to(project_dir).as_posix()
        is_reserved_database_path = rel == PROJECT_DATABASE_DUMP_NAME or (
            project_name == "infrastructure"
            and rel == INFRASTRUCTURE_DATABASE_DUMP_NAME
        )
        if _should_exclude(rel, excludes) or is_reserved_database_path:
            continue
        try:
            mode = full.lstat().st_mode
            if not (stat.S_ISREG(mode) or stat.S_ISLNK(mode)):
                continue
            if stat.S_ISLNK(mode) and not _safe_relative_symlink(
                full,
                project_dir,
                os.readlink(full),
            ):
                continue
            _add_checked_file(archive, full, f"{project_name}/{rel}")
            count += 1
        except FileNotFoundError:
            continue
    return count


def _regular_file_filter(member: tarfile.TarInfo) -> tarfile.TarInfo | None:
    """Keep archive creation aligned with the regular-file-only restore policy."""
    return member if member.isreg() else None


def _recoverable_file_filter(member: tarfile.TarInfo) -> tarfile.TarInfo | None:
    """Allow only regular files and prevalidated relative symlinks."""
    return member if member.isreg() or member.issym() else None


def payload_tree_metadata(snapshot_dir: Path) -> dict[str, Any]:
    """Measure regular bytes in the actual materialized tree without following links."""
    names: list[str] = []
    logical_bytes = 0
    def walk_error(error: OSError) -> None:
        raise error

    for root, dirs, files in os.walk(snapshot_dir, followlinks=False, onerror=walk_error):
        check_backup_cancelled()
        root_path = Path(root)
        dirs[:] = [name for name in dirs if not (root_path / name).is_symlink()]
        for name in files:
            path = root_path / name
            metadata = path.lstat()
            if stat.S_ISREG(metadata.st_mode):
                logical_bytes += metadata.st_size
                names.append(path.relative_to(snapshot_dir).as_posix())
    return {"total_bytes": logical_bytes, "logical_bytes": logical_bytes, "total_files": len(names), "tree": _archive_tree([f"payload/{name}" for name in names])}


def prepare_project_payload(
    project_dir: Path,
    project_name: str,
    staging: Path,
    env: dict[str, str],
    *,
    source_roots: dict[str, Path] | None = None,
    sensitive_paths: tuple[Path, ...] = (),
    git_bundle_reuse: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate and materialize recovery files and plain SQL in private staging.

    The caller owns staging lifetime and encryption. No tar/gzip/age is applied;
    total_bytes/logical_bytes count actual regular files including recovery data.
    Reuse is optional {'bundle_path': Path, 'git': prior_manifest['git']}.
    """
    capture_started = time.monotonic()
    backup_phase("capture")
    mode = project_dir.lstat().st_mode
    if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
        raise RuntimeError("Backup source must be a directory or explicit regular file")
    excludes = _load_excludes(project_dir)
    if project_dir.is_dir():
        excludes = (*excludes, f"./{PROJECT_DATABASE_DUMP_NAME}")
    codex_essentials = project_name == ".codex" and stat.S_ISDIR(mode)

    def capture_excludes(relative: str, patterns: tuple[str, ...]) -> bool:
        return (codex_essentials and not is_codex_recovery_input(relative)) or _should_exclude(relative, patterns)

    snapshot_dir, recovery = build_consistent_snapshot(
        project_dir, staging, excludes, capture_excludes, sensitive_paths,
        source_roots=source_roots, git_bundle_reuse=git_bundle_reuse,
        capture_git=not codex_essentials,
    )
    if codex_essentials:
        recovery["capture_profile"] = CODEX_CAPTURE_PROFILE
        (snapshot_dir / RECOVERY_DIR_NAME / RECOVERY_MANIFEST_NAME).write_text(json.dumps(recovery, indent=2, sort_keys=True) + "\n")
    db_dump = snapshot_dir / PROJECT_DATABASE_PAYLOAD_NAME
    if db_dump.exists():
        # Preserve a source SQL file at the project root; generated recovery SQL
        # then uses the already-reserved recovery directory instead of replacing
        # the original asset.
        db_dump = snapshot_dir / ".summitflow-recovery" / PROJECT_DATABASE_PAYLOAD_NAME
    # An explicitly registered configuration file has no project database.
    db_size, expects_db = (0, False) if recovery["source_kind"] == "file" or codex_essentials else _dump_database(project_name, db_dump, env)
    db_size = db_dump.stat().st_size if recovery["source_kind"] != "file" and db_dump.exists() else 0
    if db_size == 0 and expects_db:
        raise RuntimeError(f"Database dump skipped: missing credentials for {project_name}")
    metadata = payload_tree_metadata(snapshot_dir)
    verification = {
        "verified": True, "verified_at": datetime.now(UTC).isoformat(), "errors": [],
        "tree": metadata["tree"], "total_files": metadata["total_files"],
        "has_db": db_size > 0, "expects_db": expects_db, "recovery": recovery,
        "capture": {"duration_ms": int((time.monotonic() - capture_started) * 1000), "logical_bytes": metadata["logical_bytes"]},
    }
    return {
        **metadata, "snapshot_dir": snapshot_dir, "db_bytes": db_size,
        "files_bytes": metadata["total_bytes"] - db_size, "recovery": recovery,
        "expects_db": expects_db, "db_dump_name": db_dump.relative_to(snapshot_dir).as_posix(),
        "verification": verification,
    }


def _create_project_archive(
    project_dir: Path, project_name: str, staging: Path, env: dict[str, str],
    *, source_roots: dict[str, Path] | None = None,
    sensitive_paths: tuple[Path, ...] = (),
) -> dict[str, Any]:
    capture_started = time.monotonic()
    payload = prepare_project_payload(
        project_dir, project_name, staging, env,
        source_roots=source_roots, sensitive_paths=sensitive_paths,
    )
    snapshot_dir = payload["snapshot_dir"]
    recovery = payload["recovery"]
    expects_db = payload["expects_db"]
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    archive_name = f"{project_name}-{timestamp}.tar.gz"
    archive_path = staging / archive_name
    db_dump = staging / PROJECT_DATABASE_DUMP_NAME
    db_size = 0
    if payload["db_bytes"]:
        db_size = _gzip_payload_file(snapshot_dir / payload["db_dump_name"], db_dump)
    backup_phase("archive", archive_name)
    with tarfile.open(archive_path, "w:gz") as archive:
        dump_excludes = (f"./{payload['db_dump_name']}",) if payload["db_bytes"] else ()
        files_count = _add_project_files(archive, snapshot_dir, project_name, dump_excludes)
        if db_dump.exists():
            _add_checked_file(archive, db_dump, f"{project_name}/{PROJECT_DATABASE_DUMP_NAME}", regular_only=True)
            files_count += 1
    verification = verify_archive(
        archive_path,
        db_dump_name=PROJECT_DATABASE_DUMP_NAME,
        expects_db=expects_db,
    )
    verification["recovery"] = recovery
    verification["capture"] = {
        "duration_ms": int((time.monotonic() - capture_started) * 1000),
        "archive_bytes": archive_path.stat().st_size,
    }
    total_size = archive_path.stat().st_size
    return {
        "archive_name": archive_name,
        "archive_path": archive_path,
        "total_bytes": total_size,
        "logical_bytes": payload["logical_bytes"],
        "db_bytes": db_size,
        "files_bytes": max(total_size - db_size, 0),
        "total_files": files_count,
        "verification": verification,
        "recovery": recovery,
    }


def verify_archive(path: Path, *, db_dump_name: str, expects_db: bool) -> dict[str, Any]:
    names, error = _archive_member_names(path, expects_db)
    if error is not None:
        return error
    tree = _archive_tree(names)
    checksum = archive_sha256(path)
    paths = [PurePosixPath(name) for name in names]
    top_levels = {member_path.parts[0] for member_path in paths if member_path.parts}
    expected_db_name = (
        f"infrastructure/{INFRASTRUCTURE_DATABASE_DUMP_NAME}"
        if db_dump_name == INFRASTRUCTURE_DATABASE_DUMP_NAME
        else f"{next(iter(top_levels))}/{PROJECT_DATABASE_DUMP_NAME}"
        if len(top_levels) == 1
        else ""
    )
    canonical_database_names = (
        {f"infrastructure/{INFRASTRUCTURE_DATABASE_DUMP_NAME}"}
        if top_levels == {"infrastructure"}
        else {
            f"{top_level}/{PROJECT_DATABASE_DUMP_NAME}"
            for top_level in top_levels
        }
    )
    database_members = [name for name in names if name in canonical_database_names]
    has_db = database_members == [expected_db_name] and PurePosixPath(expected_db_name).name == db_dump_name
    errors: list[str] = []
    if not names:
        errors.append("Critical: archive contains no regular files")
    elif any(len(member_path.parts) < 2 for member_path in paths) or len(top_levels) != 1:
        errors.append("Critical: archive files must use exactly one top-level directory")
    if len(database_members) > 1:
        errors.append("Critical: duplicate database dumps")
    elif database_members and not has_db:
        errors.append(f"Critical: database dump must use canonical path {expected_db_name}")
    elif expects_db and not has_db:
        errors.append(f"Critical: {db_dump_name} missing")
    return {
        "verified": not errors,
        "verified_at": datetime.now(UTC).isoformat(),
        "errors": errors,
        "tree": tree,
        "total_files": len(names),
        "checksum": checksum,
        "has_db": has_db,
        "expects_db": expects_db,
    }


def archive_sha256(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    """Return a bounded-memory SHA-256 checksum for an archive."""
    digest = hashlib.sha256()
    backup_phase("checksum", path.name)
    with path.open("rb") as archive_file:
        for chunk in iter(lambda: archive_file.read(chunk_size), b""):
            check_backup_cancelled()
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _archive_member_names(path: Path, expects_db: bool) -> tuple[list[str], dict[str, Any] | None]:
    backup_phase("archive_verification", path.name)
    try:
        with path.open("rb") as raw, _CheckedReader(raw) as checked, tarfile.open(fileobj=checked, mode="r:gz") as archive:
            members = archive.getmembers()
            unsafe_members = [
                member.name
                for member in members
                if not (member.isdir() or member.isreg() or member.issym())
            ]
            if unsafe_members:
                raise RuntimeError(
                    f"Archive contains unsupported member type: {unsafe_members[0]}"
                )
            unsafe_paths = [
                member.name
                for member in members
                if not _is_safe_archive_member_name(member.name)
            ]
            if unsafe_paths:
                raise RuntimeError(f"Archive contains unsafe member path: {unsafe_paths[0]}")
            unsafe_links = [
                member.name
                for member in members
                if member.issym() and not _is_safe_archive_link(member)
            ]
            if unsafe_links:
                raise RuntimeError(f"Archive contains unsafe symbolic link: {unsafe_links[0]}")
            return [member.name for member in members if member.isfile()], None
    except BackupCancelled:
        raise
    except (tarfile.TarError, OSError, RuntimeError) as exc:
        return [], {
            "verified": False,
            "verified_at": datetime.now(UTC).isoformat(),
            "errors": [f"Archive integrity check failed: {exc}"],
            "tree": {},
            "total_files": 0,
            "checksum": "",
            "has_db": False,
            "expects_db": expects_db,
        }


def _is_safe_archive_member_name(name: str) -> bool:
    member_path = PurePosixPath(name)
    return bool(
        name
        and "\x00" not in name
        and "\\" not in name
        and not member_path.is_absolute()
        and member_path.parts
        and all(part not in {"", ".", ".."} for part in member_path.parts)
    )


def _is_safe_archive_link(member: tarfile.TarInfo) -> bool:
    target = PurePosixPath(member.linkname)
    if (
        not member.linkname
        or "\x00" in member.linkname
        or "\\" in member.linkname
        or target.is_absolute()
    ):
        return False
    member_parent = PurePosixPath(member.name).parent
    combined: list[str] = []
    for part in (*member_parent.parts, *target.parts):
        if part in {"", "."}:
            continue
        if part == "..":
            if not combined:
                return False
            combined.pop()
        else:
            combined.append(part)
    archive_root = PurePosixPath(member.name).parts[0]
    return bool(combined and combined[0] == archive_root)


def _archive_tree(names: list[str]) -> dict[str, dict[str, int]]:
    tree: dict[str, dict[str, int]] = {}
    for name in names:
        stripped = name.split("/", 1)[1] if "/" in name else name
        top = stripped.split("/", 1)[0]
        tree.setdefault(top, {"count": 0})["count"] += 1
    return tree
