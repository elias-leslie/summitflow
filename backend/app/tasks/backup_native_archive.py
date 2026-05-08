from __future__ import annotations

import fnmatch
import gzip
import hashlib
import os
import shutil
import subprocess
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

BACKUP_TIMEOUT = 600
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


def _run_gzip_stream(
    command: list[str],
    destination: Path,
    *,
    env: dict[str, str] | None,
    timeout: int,
) -> tuple[int, bytes]:
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
    # Prefer PGUSER/PGPASSWORD (typically superuser) to avoid connection-slot
    # exhaustion for non-superuser roles.
    user = os.environ.get("PGUSER", db["user"])
    password = os.environ.get("PGPASSWORD", db["password"])
    run_env = {**os.environ, **env, "PGPASSWORD": password}
    command = ["pg_dump", "-U", user, "-h", db["host"], "-p", db["port"], db["name"]]
    returncode, stderr = _run_gzip_stream(command, destination, env=run_env, timeout=BACKUP_TIMEOUT)
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
    for root, dirs, files in os.walk(project_dir):
        root_path = Path(root)
        rel_root = root_path.relative_to(project_dir).as_posix()
        rel_root = "" if rel_root == "." else rel_root
        dirs[:] = [
            dirname
            for dirname in dirs
            if not _should_exclude((Path(rel_root) / dirname).as_posix(), excludes)
        ]
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


def _create_project_archive(
    project_dir: Path,
    project_name: str,
    staging: Path,
    env: dict[str, str],
) -> dict[str, Any]:
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
    names, error = _archive_member_names(path, expects_db)
    if error is not None:
        return error
    tree = _archive_tree(names)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    has_db = any(name.endswith(db_dump_name) for name in names)
    errors = [f"Critical: {db_dump_name} missing"] if expects_db and not has_db else []
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


def _archive_member_names(path: Path, expects_db: bool) -> tuple[list[str], dict[str, Any] | None]:
    try:
        with tarfile.open(path, "r:gz") as archive:
            return [member.name for member in archive.getmembers() if member.isfile()], None
    except (tarfile.TarError, OSError) as exc:
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


def _archive_tree(names: list[str]) -> dict[str, dict[str, int]]:
    tree: dict[str, dict[str, int]] = {}
    for name in names:
        stripped = name.split("/", 1)[1] if "/" in name else name
        top = stripped.split("/", 1)[0]
        tree.setdefault(top, {"count": 0})["count"] += 1
    return tree
