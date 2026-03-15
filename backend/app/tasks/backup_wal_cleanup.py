"""WAL archive cleanup — delete old WAL segments past retention."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from ..logging_config import get_logger

logger = get_logger(__name__)

DEFAULT_WAL_ARCHIVE_DIR = "/var/lib/postgresql/wal-archive"
DEFAULT_RETENTION_DAYS = 7


def get_wal_archive_info(
    archive_dir: str = DEFAULT_WAL_ARCHIVE_DIR,
) -> dict[str, Any]:
    """Get WAL archive directory info: segment count, total size, oldest/newest.

    Returns:
        Dict with segment_count, total_size_bytes, oldest, newest.
    """
    path = Path(archive_dir)
    if not path.is_dir():
        return {
            "archive_dir": archive_dir,
            "accessible": False,
            "segment_count": 0,
            "total_size_bytes": 0,
        }

    segments = sorted(path.iterdir())
    # WAL segments are 16MB files with hex names (24 chars)
    wal_files = [f for f in segments if f.is_file() and len(f.name) == 24]

    if not wal_files:
        return {
            "archive_dir": archive_dir,
            "accessible": True,
            "segment_count": 0,
            "total_size_bytes": 0,
        }

    total_size = sum(f.stat().st_size for f in wal_files)
    oldest = min(wal_files, key=lambda f: f.stat().st_mtime)
    newest = max(wal_files, key=lambda f: f.stat().st_mtime)

    return {
        "archive_dir": archive_dir,
        "accessible": True,
        "segment_count": len(wal_files),
        "total_size_bytes": total_size,
        "oldest_segment": oldest.name,
        "oldest_mtime": oldest.stat().st_mtime,
        "newest_segment": newest.name,
        "newest_mtime": newest.stat().st_mtime,
    }


def cleanup_wal_archive(
    retention_days: int = DEFAULT_RETENTION_DAYS,
    dry_run: bool = False,
    archive_dir: str = DEFAULT_WAL_ARCHIVE_DIR,
) -> dict[str, Any]:
    """Delete WAL segments older than retention_days based on mtime.

    Args:
        retention_days: Delete segments older than this many days.
        dry_run: If True, report eligible segments without deleting.
        archive_dir: Path to the WAL archive directory.

    Returns:
        Summary with counts and sizes of deleted/eligible segments.
    """
    path = Path(archive_dir)
    if not path.is_dir():
        return {
            "status": "skipped",
            "message": f"Archive directory not accessible: {archive_dir}",
            "deleted_count": 0,
            "deleted_bytes": 0,
        }

    cutoff = time.time() - (retention_days * 86400)
    wal_files = [f for f in path.iterdir() if f.is_file() and len(f.name) == 24]
    eligible = [f for f in wal_files if f.stat().st_mtime < cutoff]

    if not eligible:
        return {
            "status": "success",
            "message": "No segments older than retention threshold",
            "total_segments": len(wal_files),
            "deleted_count": 0,
            "deleted_bytes": 0,
            "retention_days": retention_days,
        }

    eligible_bytes = sum(f.stat().st_size for f in eligible)
    eligible_names = sorted(f.name for f in eligible)

    if dry_run:
        return {
            "status": "dry_run",
            "message": f"{len(eligible)} segment(s) eligible for cleanup",
            "total_segments": len(wal_files),
            "eligible_count": len(eligible),
            "eligible_bytes": eligible_bytes,
            "eligible_segments": eligible_names,
            "retention_days": retention_days,
        }

    deleted_count = 0
    deleted_bytes = 0
    errors: list[str] = []

    for f in eligible:
        try:
            size = f.stat().st_size
            f.unlink()
            deleted_count += 1
            deleted_bytes += size
        except OSError as e:
            errors.append(f"{f.name}: {e}")

    logger.info(
        "wal_archive_cleanup_completed",
        deleted_count=deleted_count,
        deleted_bytes=deleted_bytes,
        errors=len(errors),
    )

    result: dict[str, Any] = {
        "status": "success" if not errors else "partial",
        "message": f"Deleted {deleted_count} segment(s)",
        "total_segments": len(wal_files),
        "deleted_count": deleted_count,
        "deleted_bytes": deleted_bytes,
        "remaining_segments": len(wal_files) - deleted_count,
        "retention_days": retention_days,
    }
    if errors:
        result["errors"] = errors

    return result
