"""Celery tasks for evidence cleanup.

Tasks:
- cleanup_debug_captures: Clean up old debug screenshots
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from celery import shared_task

from ..logging_config import get_logger
from ..services.evidence_manager import get_evidence_base_dir
from ..storage.connection import get_connection

logger = get_logger(__name__)


@shared_task(name="summitflow.cleanup_debug_captures")  # type: ignore[untyped-decorator]
def cleanup_debug_captures(
    project_id: str | None = None,
    max_age_days: int = 7,
    max_files: int = 20,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Clean up old debug capture files.

    Keeps the most recent N debug captures and deletes ones older than max_age_days.

    Args:
        project_id: Project to clean (None = all projects)
        max_age_days: Delete captures older than this
        max_files: Keep at least this many most recent files
        dry_run: If True, only report what would be deleted

    Returns:
        Summary dict with deleted count and freed space
    """
    logger.info(
        "cleanup_debug_captures_started",
        project_id=project_id or "all",
        max_age_days=max_age_days,
        max_files=max_files,
        dry_run=dry_run,
    )

    try:
        with get_connection() as conn, conn.cursor() as cur:
            if project_id:
                cur.execute("SELECT id FROM projects WHERE id = %s", (project_id,))
            else:
                cur.execute("SELECT id FROM projects")
            projects = [row[0] for row in cur.fetchall()]

        deleted_count = 0
        deleted_bytes = 0
        details: list[dict[str, Any]] = []

        for proj_id in projects:
            result = _cleanup_project_debug(proj_id, max_age_days, max_files, dry_run)
            deleted_count += result["deleted"]
            deleted_bytes += result["bytes"]
            details.append({"project_id": proj_id, **result})

        logger.info(
            "cleanup_debug_captures_complete",
            deleted=deleted_count,
            bytes_freed=deleted_bytes,
        )

        return {
            "status": "success",
            "dry_run": dry_run,
            "deleted": deleted_count,
            "bytes_freed": deleted_bytes,
            "details": details,
        }

    except Exception as e:
        logger.error("cleanup_debug_captures_failed", error=str(e))
        return {"status": "error", "error": str(e)}


def _cleanup_project_debug(
    project_id: str, max_age_days: int, max_files: int, dry_run: bool
) -> dict[str, int]:
    """Clean up debug captures for a single project."""
    deleted = 0
    deleted_bytes = 0

    debug_dir = get_evidence_base_dir(project_id).parent / "debug-captures"
    if not debug_dir.exists():
        return {"deleted": 0, "bytes": 0}

    cutoff = datetime.now() - timedelta(days=max_age_days)

    # Get all files sorted by modification time (newest first)
    files = sorted(
        [f for f in debug_dir.glob("*.png") if not f.is_symlink()],
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )

    # Keep the newest max_files, delete old ones
    for i, file in enumerate(files):
        if i < max_files:
            continue  # Keep recent files

        mtime = datetime.fromtimestamp(file.stat().st_mtime)
        if mtime < cutoff:
            size = file.stat().st_size
            json_file = file.with_suffix(".json")

            if dry_run:
                logger.info("would_delete", file=str(file), size=size)
            else:
                file.unlink()
                if json_file.exists():
                    json_file.unlink()
                logger.info("deleted", file=str(file), size=size)

            deleted += 1
            deleted_bytes += size

    return {"deleted": deleted, "bytes": deleted_bytes}
