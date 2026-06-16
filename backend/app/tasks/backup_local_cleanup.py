"""Local filesystem cleanup for backup archives."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..logging_config import get_logger
from ..storage import backups as backup_store
from ..storage.connection import get_cursor

logger = get_logger(__name__)

DEFAULT_RETENTION_DAYS = 14


def cleanup_local_backup_archives(
    *,
    dry_run: bool = True,
    now: datetime | None = None,
    roots: list[Path] | None = None,
    current_locations: list[str | Path] | None = None,
    sources: list[dict[str, Any]] | None = None,
    default_retention_days: int = DEFAULT_RETENTION_DAYS,
) -> dict[str, Any]:
    """Prune orphaned local backup archives older than their source retention.

    Current DB-backed backup locations are always preserved. Files are only
    considered inside configured local backup backend roots.
    """
    cleanup_now = now or datetime.now(UTC)
    cleanup_roots = _configured_local_roots() if roots is None else roots
    current = _current_backup_locations() if current_locations is None else _location_set(current_locations)
    retention_by_source = _retention_by_source(sources if sources is not None else backup_store.list_sources())

    scanned = kept_current = skipped_recent = deleted = failed = 0
    bytes_reclaimable = bytes_deleted = 0
    candidates: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []

    for root in cleanup_roots:
        if not root.exists():
            continue
        for archive in sorted(root.glob("**/*.tar.gz")):
            if not archive.is_file() or archive.is_symlink():
                continue
            scanned += 1
            archive_key = _path_key(archive)
            if archive_key in current or str(archive) in current:
                kept_current += 1
                continue

            stat = archive.stat()
            source_id = _source_id_for_archive(root, archive)
            retention_days = retention_by_source.get(source_id, default_retention_days)
            age_days = max(0, int((cleanup_now.timestamp() - stat.st_mtime) // 86400))
            if age_days < retention_days:
                skipped_recent += 1
                continue

            item = {
                "path": str(archive),
                "source_id": source_id,
                "size_bytes": stat.st_size,
                "age_days": age_days,
                "retention_days": retention_days,
            }
            candidates.append(item)
            bytes_reclaimable += stat.st_size
            if dry_run:
                continue
            try:
                archive.unlink()
                deleted += 1
                bytes_deleted += stat.st_size
            except OSError as exc:
                failed += 1
                failures.append({"path": str(archive), "error": str(exc)})

    result = {
        "status": "dry_run" if dry_run else ("partial" if failed else "success"),
        "roots": [str(root) for root in cleanup_roots],
        "scanned": scanned,
        "kept_current": kept_current,
        "skipped_recent": skipped_recent,
        "candidates": candidates,
        "candidate_count": len(candidates),
        "bytes_reclaimable": bytes_reclaimable,
        "deleted": deleted,
        "bytes_deleted": bytes_deleted,
        "failed": failed,
        "failures": failures,
    }
    logger.info(
        "local_backup_archive_cleanup_completed",
        dry_run=dry_run,
        scanned=scanned,
        candidates=len(candidates),
        deleted=deleted,
        bytes_deleted=bytes_deleted,
        failed=failed,
    )
    return result


def _configured_local_roots() -> list[Path]:
    roots: list[Path] = []
    seen: set[str] = set()
    for backend in backup_store.list_backends(enabled_only=True):
        if str(backend.get("backend_type") or "").lower() != "local":
            continue
        config = backend.get("config")
        if not isinstance(config, dict):
            continue
        root = _local_backend_archive_root(config)
        if root is None:
            continue
        key = _path_key(root)
        if key in seen:
            continue
        seen.add(key)
        roots.append(root)
    return roots


def _local_backend_archive_root(config: dict[str, Any]) -> Path | None:
    root_raw = _string_value(config.get("root_path") or config.get("base_path"))
    path_raw = _string_value(config.get("path")) or ""

    if path_raw and Path(path_raw).expanduser().is_absolute():
        return Path(path_raw).expanduser()
    if not root_raw:
        return None

    root = Path(root_raw).expanduser()
    if path_raw:
        root = root / path_raw.strip("/")
    return root


def _current_backup_locations() -> set[str]:
    with get_cursor() as cur:
        cur.execute("SELECT location FROM backups WHERE location IS NOT NULL")
        rows = cur.fetchall()
    return _location_set([row[0] for row in rows if row and row[0]])


def _location_set(locations: list[str | Path]) -> set[str]:
    result: set[str] = set()
    for location in locations:
        text = str(location).strip()
        if not text or text.startswith("//") or text == "pending_upload":
            continue
        path = Path(text).expanduser()
        result.add(str(path))
        if path.is_absolute():
            result.add(_path_key(path))
    return result


def _retention_by_source(sources: list[dict[str, Any]]) -> dict[str, int]:
    retention: dict[str, int] = {}
    for source in sources:
        source_id = str(source.get("id") or "")
        if not source_id:
            continue
        raw_days = source.get("retention_days")
        try:
            days = int(str(raw_days)) if raw_days is not None else DEFAULT_RETENTION_DAYS
        except (TypeError, ValueError):
            days = DEFAULT_RETENTION_DAYS
        retention[source_id] = max(1, days)
    return retention


def _source_id_for_archive(root: Path, archive: Path) -> str:
    try:
        relative = archive.relative_to(root)
    except ValueError:
        return archive.parent.name
    parts = relative.parts
    if len(parts) >= 2:
        return parts[0]
    return _source_id_from_archive_name(archive.name)


def _source_id_from_archive_name(name: str) -> str:
    stem = name.removesuffix(".tar.gz")
    marker = "-"
    for idx, char in enumerate(stem):
        if char == marker and stem[idx + 1 : idx + 9].isdigit():
            return stem[:idx]
    return stem


def _path_key(path: Path) -> str:
    return str(path.expanduser().resolve(strict=False))


def _string_value(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
