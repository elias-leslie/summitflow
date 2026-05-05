"""Backup archive helpers for CLI commands."""

from __future__ import annotations

import tarfile
from pathlib import Path
from typing import Any

import typer

from app.storage.backups.storage_backends import list_backends as list_storage_backends
from app.tasks.backup_native import restore_archive

from ..config import get_config
from ..lib.confirm_token import confirm_gate
from ..output import output_error, output_json
from .backup_formatters import format_size


def restore_archive_args(
    *,
    latest: bool,
    archive_file: str | None,
    archive_name: str | None,
    dry_run: bool,
    db_only: bool,
    files_only: bool,
) -> list[str]:
    targets = [latest, archive_file is not None, archive_name is not None]
    if sum(1 for target in targets if target) != 1:
        output_error("Use exactly one archive target: --latest, --file PATH, or --name ARCHIVE.")
        raise typer.Exit(1) from None

    args = _target_args(latest=latest, archive_file=archive_file, archive_name=archive_name)
    if dry_run:
        args.append("--dry-run")
    if db_only:
        args.append("--db-only")
    if files_only:
        args.append("--files-only")
    return args


def run_archive_restore(
    *,
    latest: bool,
    archive_file: str | None,
    archive_name: str | None,
    dry_run: bool,
    db_only: bool,
    files_only: bool,
    confirm: str | None,
) -> None:
    restore_archive_args(
        latest=latest,
        archive_file=archive_file,
        archive_name=archive_name,
        dry_run=dry_run,
        db_only=db_only,
        files_only=files_only,
    )
    if not dry_run:
        _confirm_restore(latest, archive_file, archive_name, db_only, files_only, confirm)
    archive = resolve_archive(latest=latest, archive_file=archive_file, archive_name=archive_name)
    if dry_run:
        preview_archive(archive, db_only=db_only, files_only=files_only)
        return
    config = get_config()
    project_root = Path(config.project_root or Path.cwd())
    result = restore_archive(archive, project_root, dry_run=False, db_only=db_only, files_only=files_only)
    output_json(result)


def archive_paths() -> list[tuple[str, Path]]:
    paths: list[tuple[str, Path]] = []
    seen: set[Path] = set()
    for label, directory in _archive_dirs():
        if directory.exists():
            pattern = "**/*.tar.gz" if label == "STORAGE" else "*.tar.gz"
            for path in sorted(directory.glob(pattern)):
                if not path.is_file():
                    continue
                resolved = path.resolve()
                if resolved in seen:
                    continue
                seen.add(resolved)
                paths.append((label, path))
    return paths


def resolve_archive(*, latest: bool, archive_file: str | None, archive_name: str | None) -> Path:
    if archive_file:
        path = Path(archive_file).expanduser()
        if path.exists():
            return path
        output_error(f"Archive not found: {archive_file}")
        raise typer.Exit(1) from None
    matches = archive_paths()
    if archive_name:
        return _named_archive(matches, archive_name)
    if latest and matches:
        return max((path for _, path in matches), key=lambda item: item.stat().st_mtime)
    output_error("No archive found")
    raise typer.Exit(1) from None


def preview_archive(path: Path, *, db_only: bool, files_only: bool, limit: int = 30) -> None:
    print(f"ARCHIVE {path}")
    print(f"MODE db_only:{str(db_only).lower()} files_only:{str(files_only).lower()}")
    shown = omitted = 0
    with tarfile.open(path, "r:gz") as archive:
        for member in archive.getmembers():
            if _skip_member(member.name, db_only=db_only, files_only=files_only):
                continue
            if shown < limit:
                print(f"  {member.name}")
                shown += 1
            else:
                omitted += 1
    if omitted:
        print(f"  ... ({omitted} more)")


def local_status_command() -> None:
    archives = archive_paths()
    if not archives:
        print("NO_LOCAL_ARCHIVES")
        return
    _, latest = max(archives, key=lambda item: item[1].stat().st_mtime)
    print(f"LOCAL_LATEST {latest.name}|{format_size(latest.stat().st_size)}|{latest}")


def list_archives_command() -> None:
    archives = archive_paths()
    print(f"ARCHIVES[{len(archives)}]")
    for label, path in archives:
        print(f"  {label} {path.name} {format_size(path.stat().st_size)} {path}")


def _target_args(*, latest: bool, archive_file: str | None, archive_name: str | None) -> list[str]:
    if latest:
        return ["--latest"]
    if archive_file:
        return ["--file", archive_file]
    if archive_name:
        return ["--name", archive_name]
    return []


def _confirm_restore(
    latest: bool,
    archive_file: str | None,
    archive_name: str | None,
    db_only: bool,
    files_only: bool,
    confirm: str | None,
) -> None:
    target = "latest" if latest else archive_file or archive_name or "unknown"
    hint = "st backup restore " + " ".join(_target_args(latest=latest, archive_file=archive_file, archive_name=archive_name))
    if db_only:
        hint += " --db-only"
    if files_only:
        hint += " --files-only"
    confirm_gate(
        f"backup-archive-restore-{target}",
        confirm,
        [
            f"RESTORE ARCHIVE: {target}",
            "This can overwrite project files and/or database state.",
            "Use --dry-run first for archive restore preview output.",
        ],
        hint,
    )


def _archive_dirs() -> list[tuple[str, Path]]:
    config = get_config()
    project_root = Path(config.project_root or Path.cwd())
    return [
        ("LOCAL", project_root / "backups"),
        ("PENDING", Path.home() / ".local" / "share" / "backup-pending"),
        *_configured_local_archive_dirs(),
    ]


def _configured_local_archive_dirs() -> list[tuple[str, Path]]:
    try:
        backends = list_storage_backends(enabled_only=True)
    except Exception:
        return []

    directories: list[tuple[str, Path]] = []
    seen: set[Path] = set()
    for backend in backends:
        if str(backend.get("backend_type") or "").lower() != "local":
            continue
        config = backend.get("config")
        if not isinstance(config, dict):
            continue
        directory = _local_backend_archive_dir(config)
        if directory is None:
            continue
        resolved = directory.expanduser().resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        directories.append(("STORAGE", directory))
    return directories


def _local_backend_archive_dir(config: dict[str, Any]) -> Path | None:
    root_raw = _string_value(config.get("root_path") or config.get("base_path"))
    path_raw = _string_value(config.get("path")) or ""

    if path_raw and Path(path_raw).expanduser().is_absolute():
        return Path(path_raw).expanduser()

    if not root_raw:
        return None

    directory = Path(root_raw).expanduser()
    if path_raw:
        directory = directory / path_raw.strip("/")
    return directory


def _string_value(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _named_archive(matches: list[tuple[str, Path]], archive_name: str) -> Path:
    for _, path in matches:
        if path.name == archive_name:
            return path
    output_error(f"Archive not found: {archive_name}")
    raise typer.Exit(1) from None


def _skip_member(name: str, *, db_only: bool, files_only: bool) -> bool:
    return (db_only and not name.endswith("database.sql.gz")) or (files_only and name.endswith("database.sql.gz"))
