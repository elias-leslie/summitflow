"""Celery tasks for evidence capture and cleanup.

Tasks:
- capture_scheduled_evidence: Refresh expired evidence for UI criteria
- cleanup_debug_captures: Clean up old debug screenshots
"""

from __future__ import annotations

import asyncio
import re
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from celery import shared_task

from ..logging_config import get_logger
from ..services.evidence_manager import capture_evidence, get_evidence_base_dir
from ..storage.connection import get_connection

logger = get_logger(__name__)


@shared_task(name="summitflow.capture_scheduled_evidence")
def capture_scheduled_evidence(
    project_id: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Capture evidence for UI criteria that need refresh.

    Finds features with UI acceptance criteria that either:
    - Have no evidence yet
    - Have evidence older than expiry threshold (default 24h)

    Args:
        project_id: Optional project to scope capture (None = all projects)
        dry_run: If True, only report what would be captured

    Returns:
        Summary dict with captured, skipped, and error counts
    """
    logger.info(
        "capture_scheduled_evidence_started",
        project_id=project_id or "all",
        dry_run=dry_run,
    )

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Get projects to process
                if project_id:
                    cur.execute(
                        "SELECT id, base_url FROM projects WHERE id = %s",
                        (project_id,),
                    )
                else:
                    cur.execute("SELECT id, base_url FROM projects")
                projects = cur.fetchall()

        captured = 0
        skipped = 0
        errors = 0
        details: list[dict[str, Any]] = []

        for proj_id, base_url in projects:
            result = _capture_for_project(proj_id, base_url, dry_run)
            captured += result["captured"]
            skipped += result["skipped"]
            errors += result["errors"]
            details.append({"project_id": proj_id, **result})

        logger.info(
            "capture_scheduled_evidence_complete",
            captured=captured,
            skipped=skipped,
            errors=errors,
        )

        return {
            "status": "success",
            "dry_run": dry_run,
            "captured": captured,
            "skipped": skipped,
            "errors": errors,
            "details": details,
        }

    except Exception as e:
        logger.error("capture_scheduled_evidence_failed", error=str(e))
        return {"status": "error", "error": str(e)}


def _capture_for_project(
    project_id: str, base_url: str, dry_run: bool
) -> dict[str, int]:
    """Capture evidence for a single project."""
    captured = 0
    skipped = 0
    errors = 0

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Find UI criteria needing evidence
                # Join features with acceptance_criteria JSONB
                cur.execute(
                    """
                    SELECT
                        fc.feature_id,
                        fc.name,
                        ac.value->>'id' as criterion_id,
                        ac.value->>'criterion' as criterion_text,
                        ac.value->>'verification' as verification_url
                    FROM feature_capabilities fc,
                         jsonb_array_elements(fc.acceptance_criteria) as ac(value)
                    WHERE fc.project_id = %s
                      AND ac.value->>'type' = 'ui'
                    ORDER BY fc.feature_id, ac.value->>'id'
                    """,
                    (project_id,),
                )
                criteria = cur.fetchall()

        if not criteria:
            logger.info("no_ui_criteria_found", project_id=project_id)
            return {"captured": 0, "skipped": 0, "errors": 0}

        # Check each criterion for evidence freshness
        expiry_threshold = datetime.now(timezone.utc) - timedelta(hours=24)

        for feature_id, name, criterion_id, criterion_text, verification_url in criteria:
            try:
                # Check if evidence exists and is fresh
                with get_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            SELECT captured_at FROM evidence
                            WHERE project_id = %s
                              AND feature_id = %s
                              AND criterion_id = %s
                              AND is_current = TRUE
                            ORDER BY captured_at DESC
                            LIMIT 1
                            """,
                            (project_id, feature_id, criterion_id),
                        )
                        row = cur.fetchone()

                if row and row[0] and row[0] > expiry_threshold:
                    skipped += 1
                    continue

                # Determine URL to capture
                url = verification_url or f"{base_url}/"

                if dry_run:
                    logger.info(
                        "would_capture",
                        feature_id=feature_id,
                        criterion_id=criterion_id,
                        url=url,
                    )
                    captured += 1
                    continue

                # Capture evidence
                result = asyncio.run(
                    capture_evidence(project_id, url, feature_id, criterion_id)
                )

                if result.get("success"):
                    captured += 1
                    logger.info(
                        "evidence_captured",
                        feature_id=feature_id,
                        criterion_id=criterion_id,
                        version=result.get("version"),
                    )
                else:
                    errors += 1
                    logger.warning(
                        "evidence_capture_failed",
                        feature_id=feature_id,
                        criterion_id=criterion_id,
                        error=result.get("error"),
                    )

            except Exception as e:
                errors += 1
                logger.error(
                    "criterion_capture_error",
                    feature_id=feature_id,
                    criterion_id=criterion_id,
                    error=str(e),
                )

    except Exception as e:
        logger.error("project_capture_error", project_id=project_id, error=str(e))
        errors += 1

    return {"captured": captured, "skipped": skipped, "errors": errors}


@shared_task(name="summitflow.cleanup_debug_captures")
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
        with get_connection() as conn:
            with conn.cursor() as cur:
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
