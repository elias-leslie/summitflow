"""Evidence Manager - Service for managing UI verification evidence.

This module provides functions to:
- Save and retrieve evidence (screenshots + evidence.json)
- Track evidence versions
- Manage AI and user reviews
- Clean up old versions

Evidence is stored at: {project_data_dir}/evidence/{capability_id}/{criterion_id}/v{n}/
Each version contains:
  - screenshot.png: Full page screenshot
  - evidence.json: Console, network, page state, performance data

Extracted from portfolio-ai/backend/app/services/artifact_manager.py
Changes from source:
  - Renamed "artifacts" -> "evidence" throughout
  - Added project_id parameter to all functions
  - Uses get_connection() context manager
  - Evidence paths are project-relative
"""

from __future__ import annotations

import asyncio
import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from ..logging_config import get_logger
from ..storage.connection import get_connection

logger = get_logger(__name__)

# Configuration defaults (can be overridden per-project)
DEFAULT_EXPIRY_HOURS = 24
MAX_VERSIONS_TO_KEEP = 5
CAPTURE_TIMEOUT_SECONDS = 60


def get_evidence_base_dir(project_id: str) -> Path:
    """Get evidence base directory for a project.

    TODO: Fetch from project config in database.
    For now, use a standard path structure.
    """
    # TODO: Query projects table for data_dir and use that
    return Path(f"/home/kasadis/summitflow/data/projects/{project_id}/evidence")


def get_browser_scripts_dir(project_id: str) -> Path:
    """Get browser scripts directory for a project.

    TODO: Fetch from project config in database.
    """
    # TODO: Query projects table for browser_scripts_dir
    return Path("/home/kasadis/summitflow/.claude/skills/browser-automation/scripts")


def generate_evidence_id(capability_id: str, criterion_id: str, version: int) -> str:
    """Generate a unique evidence ID."""
    return f"{capability_id}-{criterion_id}-v{version}"


async def capture_evidence(
    project_id: str,
    url: str,
    capability_id: str,
    criterion_id: str,
) -> dict[str, Any]:
    """Capture evidence for a UI criterion using the capture-evidence.js script.

    Args:
        project_id: Project ID for scoping
        url: The full URL to capture
        capability_id: Capability ID (e.g., login, password-reset)
        criterion_id: Criterion ID (e.g., ac-001)

    Returns:
        Dict with success, version, file_path, evidence data
    """
    scripts_dir = get_browser_scripts_dir(project_id)
    script_path = scripts_dir / "capture-evidence.js"
    evidence_base = get_evidence_base_dir(project_id)

    if not script_path.exists():
        return {
            "success": False,
            "error": f"Capture script not found: {script_path}",
        }

    # Ensure evidence directory exists
    evidence_base.mkdir(parents=True, exist_ok=True)

    try:
        proc = await asyncio.create_subprocess_exec(
            "node",
            str(script_path),
            url,
            capability_id,
            criterion_id,
            str(evidence_base),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, _stderr = await asyncio.wait_for(
            proc.communicate(),
            timeout=CAPTURE_TIMEOUT_SECONDS,
        )

        output = stdout.decode()

        # Parse JSON result from script output
        result_line = None
        for line in output.split("\n"):
            if line.startswith("{") and '"success"' in line:
                result_line = line
                break

        if result_line:
            parsed: dict[str, Any] = json.loads(result_line)
            return parsed

        return {
            "success": False,
            "error": f"Could not parse script output: {output[:500]}",
        }

    except TimeoutError:
        return {
            "success": False,
            "error": f"Capture timed out after {CAPTURE_TIMEOUT_SECONDS}s",
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


def save_evidence(
    project_id: str,
    capability_id: str,
    criterion_id: str,
    version: int,
    file_path: str,
    file_size_bytes: int | None = None,
    evidence_data: dict[str, Any] | None = None,
    expires_hours: int = DEFAULT_EXPIRY_HOURS,
) -> dict[str, Any]:
    """Save an evidence record to the database.

    Args:
        project_id: Project ID for scoping
        capability_id: Feature ID (e.g., FEAT-001)
        criterion_id: Criterion ID (e.g., ac-001)
        version: Version number
        file_path: Relative path to evidence directory
        file_size_bytes: Total size of files
        evidence_data: Parsed evidence.json data
        expires_hours: Hours until evidence expires

    Returns:
        Created evidence record
    """
    evidence_id = generate_evidence_id(capability_id, criterion_id, version)
    expires_at = datetime.now(UTC) + timedelta(hours=expires_hours)

    with get_connection() as conn, conn.cursor() as cur:
        # Mark previous versions as not current
        cur.execute(
            """
            UPDATE evidence
            SET is_current = FALSE, updated_at = NOW()
            WHERE project_id = %s AND capability_id = %s AND criterion_id = %s AND is_current = TRUE
            """,
            (project_id, capability_id, criterion_id),
        )

        # Insert new evidence
        cur.execute(
            """
            INSERT INTO evidence (
                project_id, evidence_id, capability_id, criterion_id, evidence_type,
                file_path, file_size_bytes, version, is_current,
                captured_at, expires_at, quality_status
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, TRUE, NOW(), %s, 'pending')
            RETURNING id, evidence_id, captured_at
            """,
            (
                project_id,
                evidence_id,
                capability_id,
                criterion_id,
                "evidence",
                file_path,
                file_size_bytes,
                version,
                expires_at,
            ),
        )
        result = cur.fetchone()
        conn.commit()

        if not result:
            raise RuntimeError("Failed to create evidence record")

        logger.info(
            "evidence_saved",
            project_id=project_id,
            evidence_id=evidence_id,
            capability_id=capability_id,
            criterion_id=criterion_id,
            version=version,
        )

        captured_ts = result[2]
        captured_iso: str | None = None
        if captured_ts is not None and isinstance(captured_ts, datetime):
            captured_iso = captured_ts.isoformat()

        return {
            "id": result[0],
            "evidence_id": result[1],
            "captured_at": captured_iso,
            "version": version,
            "file_path": file_path,
        }


def get_evidence(
    project_id: str,
    capability_id: str,
    criterion_id: str,
    version: int | None = None,
) -> dict[str, Any] | None:
    """Get evidence metadata (current version or specific version).

    Args:
        project_id: Project ID for scoping
        capability_id: Feature ID
        criterion_id: Criterion ID
        version: Optional specific version (defaults to current)

    Returns:
        Evidence record or None
    """
    with get_connection() as conn, conn.cursor() as cur:
        if version:
            cur.execute(
                """
                SELECT id, evidence_id, capability_id, criterion_id, evidence_type,
                       file_path, file_size_bytes, version, is_current,
                       captured_at, expires_at, quality_status, quality_issues,
                       confidence, ai_reviewed_at, ai_reviewed_by, ai_evidence,
                       user_reviewed_at, user_approved, user_notes
                FROM evidence
                WHERE project_id = %s AND capability_id = %s AND criterion_id = %s AND version = %s
                """,
                (project_id, capability_id, criterion_id, version),
            )
        else:
            cur.execute(
                """
                SELECT id, evidence_id, capability_id, criterion_id, evidence_type,
                       file_path, file_size_bytes, version, is_current,
                       captured_at, expires_at, quality_status, quality_issues,
                       confidence, ai_reviewed_at, ai_reviewed_by, ai_evidence,
                       user_reviewed_at, user_approved, user_notes
                FROM evidence
                WHERE project_id = %s AND capability_id = %s AND criterion_id = %s AND is_current = TRUE
                """,
                (project_id, capability_id, criterion_id),
            )
        row = cur.fetchone()

        if not row:
            return None

        return _row_to_evidence(row)


def get_latest_evidence(project_id: str) -> dict[str, Any] | None:
    """Get the most recently captured evidence for a project.

    Args:
        project_id: Project ID for scoping

    Returns:
        Most recent evidence record or None
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, evidence_id, capability_id, criterion_id, evidence_type,
                   file_path, file_size_bytes, version, is_current,
                   captured_at, expires_at, quality_status, quality_issues,
                   confidence, ai_reviewed_at, ai_reviewed_by, ai_evidence,
                   user_reviewed_at, user_approved, user_notes
            FROM evidence
            WHERE project_id = %s AND is_current = TRUE
            ORDER BY captured_at DESC
            LIMIT 1
            """,
            (project_id,),
        )
        row = cur.fetchone()

        if not row:
            return None

        return _row_to_evidence(row)


def get_next_version(project_id: str, capability_id: str, criterion_id: str) -> int:
    """Get the next version number for a feature/criterion pair.

    Args:
        project_id: Project ID for scoping
        capability_id: Feature ID
        criterion_id: Criterion ID

    Returns:
        Next version number (1 if no existing versions)
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT MAX(version) as max_version
            FROM evidence
            WHERE project_id = %s AND capability_id = %s AND criterion_id = %s
            """,
            (project_id, capability_id, criterion_id),
        )
        row = cur.fetchone()

        if row and row[0]:
            return row[0] + 1
        return 1


def get_evidence_versions(
    project_id: str,
    capability_id: str,
    criterion_id: str,
) -> list[dict[str, Any]]:
    """Get all versions of evidence for a criterion.

    Args:
        project_id: Project ID for scoping
        capability_id: Feature ID
        criterion_id: Criterion ID

    Returns:
        List of evidence records ordered by version desc
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, evidence_id, capability_id, criterion_id, evidence_type,
                   file_path, file_size_bytes, version, is_current,
                   captured_at, expires_at, quality_status, quality_issues,
                   confidence, ai_reviewed_at, ai_reviewed_by, ai_evidence,
                   user_reviewed_at, user_approved, user_notes
            FROM evidence
            WHERE project_id = %s AND capability_id = %s AND criterion_id = %s
            ORDER BY version DESC
            """,
            (project_id, capability_id, criterion_id),
        )
        rows = cur.fetchall()

        return [_row_to_evidence(row) for row in rows]


def list_evidence(
    project_id: str,
    limit: int = 100,
    offset: int = 0,
    capability_id: str | None = None,
    quality_status: str | None = None,
    search: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """List all current evidence for a project with filtering.

    Args:
        project_id: Project ID for scoping
        limit: Maximum number of results
        offset: Offset for pagination
        capability_id: Optional filter by feature ID
        quality_status: Optional filter by quality status
        search: Optional search term (matches capability_id, criterion_id)

    Returns:
        Tuple of (list of evidence records, total count)
    """
    with get_connection() as conn, conn.cursor() as cur:
        # Build WHERE clause
        where_clauses = ["project_id = %s", "is_current = TRUE"]
        params: list[Any] = [project_id]

        if capability_id:
            where_clauses.append("capability_id = %s")
            params.append(capability_id)

        if quality_status:
            where_clauses.append("quality_status = %s")
            params.append(quality_status)

        if search:
            where_clauses.append(
                "(capability_id ILIKE %s OR criterion_id ILIKE %s OR evidence_id ILIKE %s)"
            )
            search_pattern = f"%{search}%"
            params.extend([search_pattern, search_pattern, search_pattern])

        where_sql = " AND ".join(where_clauses)

        # Get total count
        cur.execute(f"SELECT COUNT(*) FROM evidence WHERE {where_sql}", params)
        count_row = cur.fetchone()
        total = int(count_row[0]) if count_row and count_row[0] else 0

        # Get paginated results
        params.extend([limit, offset])
        cur.execute(
            f"""
            SELECT id, evidence_id, capability_id, criterion_id, evidence_type,
                   file_path, file_size_bytes, version, is_current,
                   captured_at, expires_at, quality_status, quality_issues,
                   confidence, ai_reviewed_at, ai_reviewed_by, ai_evidence,
                   user_reviewed_at, user_approved, user_notes
            FROM evidence
            WHERE {where_sql}
            ORDER BY captured_at DESC
            LIMIT %s OFFSET %s
            """,
            params,
        )
        rows = cur.fetchall()

        return [_row_to_evidence(row) for row in rows], total


def get_pending_review(project_id: str, limit: int = 50) -> list[dict[str, Any]]:
    """Get evidence pending AI review.

    Args:
        project_id: Project ID for scoping
        limit: Maximum number of results

    Returns:
        List of evidence with quality_status = 'pending'
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, evidence_id, capability_id, criterion_id, evidence_type,
                   file_path, file_size_bytes, version, is_current,
                   captured_at, expires_at, quality_status, quality_issues,
                   confidence, ai_reviewed_at, ai_reviewed_by, ai_evidence,
                   user_reviewed_at, user_approved, user_notes
            FROM evidence
            WHERE project_id = %s AND quality_status = 'pending' AND is_current = TRUE
            ORDER BY captured_at DESC
            LIMIT %s
            """,
            (project_id, limit),
        )
        rows = cur.fetchall()

        return [_row_to_evidence(row) for row in rows]


def get_needs_user_review(project_id: str, limit: int = 50) -> list[dict[str, Any]]:
    """Get evidence that needs user review (low confidence or flagged).

    Args:
        project_id: Project ID for scoping
        limit: Maximum number of results

    Returns:
        List of evidence with quality_status = 'needs_review'
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, evidence_id, capability_id, criterion_id, evidence_type,
                   file_path, file_size_bytes, version, is_current,
                   captured_at, expires_at, quality_status, quality_issues,
                   confidence, ai_reviewed_at, ai_reviewed_by, ai_evidence,
                   user_reviewed_at, user_approved, user_notes
            FROM evidence
            WHERE project_id = %s AND quality_status = 'needs_review' AND is_current = TRUE
            ORDER BY captured_at DESC
            LIMIT %s
            """,
            (project_id, limit),
        )
        rows = cur.fetchall()

        return [_row_to_evidence(row) for row in rows]


def get_with_user_notes(project_id: str, limit: int = 50) -> list[dict[str, Any]]:
    """Get evidence that has user notes/feedback.

    Args:
        project_id: Project ID for scoping
        limit: Maximum number of results

    Returns:
        List of evidence with user_notes IS NOT NULL
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, evidence_id, capability_id, criterion_id, evidence_type,
                   file_path, file_size_bytes, version, is_current,
                   captured_at, expires_at, quality_status, quality_issues,
                   confidence, ai_reviewed_at, ai_reviewed_by, ai_evidence,
                   user_reviewed_at, user_approved, user_notes
            FROM evidence
            WHERE project_id = %s AND user_notes IS NOT NULL AND is_current = TRUE
            ORDER BY user_reviewed_at DESC
            LIMIT %s
            """,
            (project_id, limit),
        )
        rows = cur.fetchall()

        return [_row_to_evidence(row) for row in rows]


def update_ai_review(
    project_id: str,
    evidence_id: str,
    quality_status: str,
    confidence: float,
    ai_evidence: str | None = None,
    quality_issues: list[str] | None = None,
    reviewed_by: str = "claude",
) -> bool:
    """Record AI review result for evidence.

    Args:
        project_id: Project ID for scoping
        evidence_id: The evidence ID
        quality_status: New status ('passed', 'failed', 'needs_review')
        confidence: Confidence score 0.0-1.0
        ai_evidence: AI's reasoning/notes
        quality_issues: List of detected issues
        reviewed_by: Model/agent name

    Returns:
        True if updated successfully
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE evidence
            SET quality_status = %s,
                confidence = %s,
                ai_evidence = %s,
                quality_issues = %s,
                ai_reviewed_at = NOW(),
                ai_reviewed_by = %s,
                updated_at = NOW()
            WHERE project_id = %s AND evidence_id = %s
            RETURNING id
            """,
            (
                quality_status,
                confidence,
                ai_evidence,
                json.dumps(quality_issues) if quality_issues else "[]",
                reviewed_by,
                project_id,
                evidence_id,
            ),
        )
        result = cur.fetchone()
        conn.commit()

        if result:
            logger.info(
                "ai_review_recorded",
                project_id=project_id,
                evidence_id=evidence_id,
                quality_status=quality_status,
                confidence=confidence,
            )
            return True

        return False


def update_user_review(
    project_id: str,
    evidence_id: str,
    approved: bool | None,
    notes: str | None = None,
) -> bool:
    """Record user review for evidence.

    Args:
        project_id: Project ID for scoping
        evidence_id: The evidence ID
        approved: True=approved, False=rejected, None=pending
        notes: User feedback/notes

    Returns:
        True if updated successfully
    """
    # Also update quality_status based on user decision
    new_status = None
    if approved is True:
        new_status = "passed"
    elif approved is False:
        new_status = "failed"

    with get_connection() as conn, conn.cursor() as cur:
        if new_status:
            cur.execute(
                """
                UPDATE evidence
                SET user_approved = %s,
                    user_notes = %s,
                    user_reviewed_at = NOW(),
                    quality_status = %s,
                    updated_at = NOW()
                WHERE project_id = %s AND evidence_id = %s
                RETURNING id
                """,
                (approved, notes, new_status, project_id, evidence_id),
            )
        else:
            cur.execute(
                """
                UPDATE evidence
                SET user_notes = %s,
                    user_reviewed_at = NOW(),
                    updated_at = NOW()
                WHERE project_id = %s AND evidence_id = %s
                RETURNING id
                """,
                (notes, project_id, evidence_id),
            )
        result = cur.fetchone()
        conn.commit()

        if result:
            logger.info(
                "user_review_recorded",
                project_id=project_id,
                evidence_id=evidence_id,
                approved=approved,
            )
            return True

        return False


def get_expired_evidence(project_id: str) -> list[dict[str, Any]]:
    """Get evidence that has expired and needs refresh.

    Args:
        project_id: Project ID for scoping

    Returns:
        List of expired current evidence
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, evidence_id, capability_id, criterion_id, evidence_type,
                   file_path, file_size_bytes, version, is_current,
                   captured_at, expires_at, quality_status, quality_issues,
                   confidence, ai_reviewed_at, ai_reviewed_by, ai_evidence,
                   user_reviewed_at, user_approved, user_notes
            FROM evidence
            WHERE project_id = %s AND expires_at < NOW() AND is_current = TRUE
            ORDER BY expires_at ASC
            """,
            (project_id,),
        )
        rows = cur.fetchall()

        return [_row_to_evidence(row) for row in rows]


def cleanup_old_versions(
    project_id: str,
    capability_id: str | None = None,
    max_versions: int = MAX_VERSIONS_TO_KEEP,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Delete old evidence versions beyond retention limit.

    Args:
        project_id: Project ID for scoping
        capability_id: Optional filter by feature
        max_versions: Max versions to keep per criterion
        dry_run: If True, only report what would be deleted

    Returns:
        Summary of cleanup operation
    """
    evidence_base = get_evidence_base_dir(project_id)
    deleted_count = 0
    deleted_size = 0

    with get_connection() as conn, conn.cursor() as cur:
        # Get all feature/criterion pairs
        if capability_id:
            cur.execute(
                """
                SELECT DISTINCT capability_id, criterion_id
                FROM evidence
                WHERE project_id = %s AND capability_id = %s
                """,
                (project_id, capability_id),
            )
        else:
            cur.execute(
                """
                SELECT DISTINCT capability_id, criterion_id
                FROM evidence
                WHERE project_id = %s
                """,
                (project_id,),
            )
        pairs = cur.fetchall()

        for feat_id, crit_id in pairs:
            # Get versions to delete (keep only max_versions)
            cur.execute(
                """
                SELECT id, evidence_id, file_path, file_size_bytes, version
                FROM evidence
                WHERE project_id = %s AND capability_id = %s AND criterion_id = %s
                ORDER BY version DESC
                OFFSET %s
                """,
                (project_id, feat_id, crit_id, max_versions),
            )
            old_versions = cur.fetchall()

            for row in old_versions:
                ev_id, _evidence_id, _file_path, size, version_val = row

                if not dry_run:
                    # Delete files
                    version_str = str(version_val) if version_val is not None else "0"
                    version_dir = evidence_base / str(feat_id) / str(crit_id) / f"v{version_str}"
                    if version_dir.exists():
                        shutil.rmtree(version_dir)

                    # Delete database record
                    cur.execute(
                        "DELETE FROM evidence WHERE id = %s",
                        (ev_id,),
                    )

                deleted_count += 1
                if isinstance(size, int | float):
                    deleted_size += int(size)

        if not dry_run:
            conn.commit()

    logger.info(
        "cleanup_old_versions",
        project_id=project_id,
        deleted_count=deleted_count,
        deleted_size_bytes=deleted_size,
        dry_run=dry_run,
    )

    return {
        "deleted_count": deleted_count,
        "deleted_size_bytes": deleted_size,
        "dry_run": dry_run,
    }


def get_summary(project_id: str) -> dict[str, Any]:
    """Get summary statistics for evidence in a project.

    Args:
        project_id: Project ID for scoping

    Returns:
        Dict with counts and breakdowns
    """
    with get_connection() as conn, conn.cursor() as cur:
        # Total count
        cur.execute(
            "SELECT COUNT(*) FROM evidence WHERE project_id = %s AND is_current = TRUE",
            (project_id,),
        )
        total_row = cur.fetchone()
        total = int(total_row[0]) if total_row and total_row[0] else 0

        # By status
        cur.execute(
            """
            SELECT quality_status, COUNT(*)
            FROM evidence
            WHERE project_id = %s AND is_current = TRUE
            GROUP BY quality_status
            """,
            (project_id,),
        )
        status_rows = cur.fetchall()
        by_status = {}
        for row in status_rows:
            if row[1] is not None:
                by_status[str(row[0])] = int(row[1])

        # Expired count
        cur.execute(
            """
            SELECT COUNT(*) FROM evidence
            WHERE project_id = %s AND is_current = TRUE AND expires_at < NOW()
            """,
            (project_id,),
        )
        expired_row = cur.fetchone()
        expired = int(expired_row[0]) if expired_row and expired_row[0] else 0

        # With user feedback
        cur.execute(
            """
            SELECT COUNT(*) FROM evidence
            WHERE project_id = %s AND is_current = TRUE AND user_notes IS NOT NULL
            """,
            (project_id,),
        )
        notes_row = cur.fetchone()
        with_notes = int(notes_row[0]) if notes_row and notes_row[0] else 0

        # Total storage size
        cur.execute(
            """
            SELECT COALESCE(SUM(file_size_bytes), 0) FROM evidence
            WHERE project_id = %s
            """,
            (project_id,),
        )
        size_row = cur.fetchone()
        total_size = int(size_row[0]) if size_row and size_row[0] else 0

        return {
            "total_current": total,
            "by_status": by_status,
            "expired_count": expired,
            "with_user_notes": with_notes,
            "total_storage_bytes": total_size,
        }


def read_evidence_file(
    project_id: str,
    capability_id: str,
    criterion_id: str,
    version: int | None = None,
) -> dict[str, Any] | None:
    """Read the evidence.json file for evidence.

    Args:
        project_id: Project ID for scoping
        capability_id: Feature ID
        criterion_id: Criterion ID
        version: Optional version (defaults to current)

    Returns:
        Parsed evidence.json data or None
    """
    evidence_base = get_evidence_base_dir(project_id)

    if version:
        evidence_path = (
            evidence_base / capability_id / criterion_id / f"v{version}" / "evidence.json"
        )
    else:
        evidence_path = evidence_base / capability_id / criterion_id / "current" / "evidence.json"

    if not evidence_path.exists():
        return None

    try:
        with evidence_path.open() as f:
            data: dict[str, Any] = json.load(f)
            return data
    except Exception as e:
        logger.error("read_evidence_failed", path=str(evidence_path), error=str(e))
        return None


def _row_to_evidence(row: tuple[Any, ...]) -> dict[str, Any]:
    """Convert database row to evidence dict."""
    return {
        "id": row[0],
        "evidence_id": row[1],
        "capability_id": row[2],
        "criterion_id": row[3],
        "evidence_type": row[4],
        "file_path": row[5],
        "file_size_bytes": row[6],
        "version": row[7],
        "is_current": row[8],
        "captured_at": row[9].isoformat() if row[9] else None,
        "expires_at": row[10].isoformat() if row[10] else None,
        "quality_status": row[11],
        "quality_issues": row[12] if row[12] else [],
        "confidence": row[13],
        "ai_reviewed_at": row[14].isoformat() if row[14] else None,
        "ai_reviewed_by": row[15],
        "ai_evidence": row[16],
        "user_reviewed_at": row[17].isoformat() if row[17] else None,
        "user_approved": row[18],
        "user_notes": row[19],
    }


# ============================================================
# Test Evidence Integration
# ============================================================


def register_test_evidence(
    project_id: str,
    test_id: str,
    test_run_id: int,
    evidence_path: str,
    capability_id: str | None = None,
) -> dict[str, Any] | None:
    """Register evidence from a UI test run.

    Creates an evidence record linked to a test run. Uses test_id as capability_id
    and "test-run" as criterion_id for test-generated evidence.

    Args:
        project_id: Project ID for scoping
        test_id: The test ID (used as capability_id for evidence)
        test_run_id: The test_runs table ID for linking
        evidence_path: Path to the evidence file (screenshot, etc.)
        capability_id: Optional capability ID if test is linked to one

    Returns:
        Created evidence record or None if path doesn't exist
    """
    from pathlib import Path as PathLib

    evidence_file = PathLib(evidence_path)
    if not evidence_file.exists():
        logger.warning(
            "test_evidence_not_found",
            project_id=project_id,
            test_id=test_id,
            path=evidence_path,
        )
        return None

    # Use test_id as capability_id and "test-run-{id}" as criterion for uniqueness
    capability_id = f"test-{test_id}"
    criterion_id = f"run-{test_run_id}"

    # Get next version
    version = get_next_version(project_id, capability_id, criterion_id)

    # Get file size
    file_size = evidence_file.stat().st_size if evidence_file.exists() else 0

    # Copy evidence to standard location
    evidence_base = get_evidence_base_dir(project_id)
    dest_dir = evidence_base / capability_id / criterion_id / f"v{version}"
    dest_dir.mkdir(parents=True, exist_ok=True)

    dest_path = dest_dir / evidence_file.name
    shutil.copy2(evidence_file, dest_path)

    # Save evidence record
    result = save_evidence(
        project_id=project_id,
        capability_id=capability_id,
        criterion_id=criterion_id,
        version=version,
        file_path=str(dest_dir.relative_to(evidence_base)),
        file_size_bytes=file_size,
        expires_hours=DEFAULT_EXPIRY_HOURS * 7,  # Keep test evidence longer
    )

    # Update test_runs with evidence_path
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE test_runs
            SET evidence_path = %s, updated_at = NOW()
            WHERE id = %s
            """,
            (str(dest_path), test_run_id),
        )
        conn.commit()

    logger.info(
        "test_evidence_registered",
        project_id=project_id,
        test_id=test_id,
        test_run_id=test_run_id,
        evidence_id=result.get("evidence_id"),
        version=version,
    )

    return result


def get_test_evidence(
    project_id: str,
    test_id: str,
    test_run_id: int | None = None,
) -> list[dict[str, Any]]:
    """Get evidence for a test or test run.

    Args:
        project_id: Project ID for scoping
        test_id: The test ID
        test_run_id: Optional specific test run ID

    Returns:
        List of evidence records
    """
    capability_id = f"test-{test_id}"

    if test_run_id:
        criterion_id = f"run-{test_run_id}"
        return get_evidence_versions(project_id, capability_id, criterion_id)

    # Get all evidence for this test
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, evidence_id, capability_id, criterion_id, evidence_type,
                   file_path, file_size_bytes, version, is_current,
                   captured_at, expires_at, quality_status, quality_issues,
                   confidence, ai_reviewed_at, ai_reviewed_by, ai_evidence,
                   user_reviewed_at, user_approved, user_notes
            FROM evidence
            WHERE project_id = %s AND capability_id = %s AND is_current = TRUE
            ORDER BY captured_at DESC
            """,
            (project_id, capability_id),
        )
        rows = cur.fetchall()

        return [_row_to_evidence(row) for row in rows]
