"""Evidence Storage - Database operations for evidence management.

This module handles all database interactions for evidence records:
- CRUD operations for evidence
- Query filtering and pagination
- Review status updates
- Aggregation queries
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from psycopg import sql

from .connection import get_connection

# Base SELECT columns for evidence queries (without JOIN)
EVIDENCE_SELECT_COLUMNS = """id, evidence_id, capability_id, criterion_id, evidence_type,
       file_path, file_size_bytes, version, is_current,
       captured_at, quality_status, quality_issues,
       confidence, ai_reviewed_at, ai_reviewed_by, ai_evidence,
       user_reviewed_at, user_approved, user_notes,
       criterion_db_id, test_run_id, auto_captured"""

# SELECT columns with LEFT JOIN to acceptance_criteria for criterion text
EVIDENCE_SELECT_WITH_CRITERION = """e.id, e.evidence_id, e.capability_id, e.criterion_id, e.evidence_type,
       e.file_path, e.file_size_bytes, e.version, e.is_current,
       e.captured_at, e.quality_status, e.quality_issues,
       e.confidence, e.ai_reviewed_at, e.ai_reviewed_by, e.ai_evidence,
       e.user_reviewed_at, e.user_approved, e.user_notes,
       e.criterion_db_id, e.test_run_id, e.auto_captured,
       ac.criterion as criterion_text"""


def _row_to_evidence(
    row: tuple[Any, ...], *, include_criterion_text: bool = False
) -> dict[str, Any]:
    """Convert database row to evidence dict.

    Args:
        row: Database row tuple
        include_criterion_text: If True, expects row[22] to contain criterion text from JOIN
    """
    result = {
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
        "quality_status": row[10],
        "quality_issues": row[11] if row[11] else [],
        "confidence": row[12],
        "ai_reviewed_at": row[13].isoformat() if row[13] else None,
        "ai_reviewed_by": row[14],
        "ai_evidence": row[15],
        "user_reviewed_at": row[16].isoformat() if row[16] else None,
        "user_approved": row[17],
        "user_notes": row[18],
        "criterion_db_id": row[19],
        "test_run_id": row[20],
        "auto_captured": row[21],
    }
    if include_criterion_text and len(row) > 22:
        result["criterion_text"] = row[22]
    return result


# ============================================================
# Internal helper functions (used within transactions)
# ============================================================


def mark_previous_as_stale(
    cur: Any,
    project_id: str,
    capability_id: str,
    criterion_id: str,
) -> None:
    """Mark previous evidence versions as not current."""
    cur.execute(
        """
        UPDATE evidence
        SET is_current = FALSE, updated_at = NOW()
        WHERE project_id = %s AND capability_id = %s AND criterion_id = %s AND is_current = TRUE
        """,
        (project_id, capability_id, criterion_id),
    )


def insert_evidence_record(
    cur: Any,
    project_id: str,
    evidence_id: str,
    capability_id: str,
    criterion_id: str,
    file_path: str,
    file_size_bytes: int | None,
    version: int,
    criterion_db_id: int | None = None,
    test_run_id: int | None = None,
    auto_captured: bool = False,
) -> tuple[int, str, datetime | None]:
    """Insert a new evidence record and return (id, evidence_id, captured_at).

    Args:
        cur: Database cursor
        project_id: Project ID
        evidence_id: Evidence ID
        capability_id: Capability ID (text)
        criterion_id: Criterion ID (text, e.g., 'ac-001')
        file_path: Path to evidence file
        file_size_bytes: Size of evidence file
        version: Version number
        criterion_db_id: FK to acceptance_criteria.id (optional)
        test_run_id: FK to test_runs.id if captured during test run (optional)
        auto_captured: True if evidence was auto-captured on test pass
    """
    cur.execute(
        """
        INSERT INTO evidence (
            project_id, evidence_id, capability_id, criterion_id, evidence_type,
            file_path, file_size_bytes, version, is_current,
            captured_at, quality_status, criterion_db_id, test_run_id, auto_captured
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, TRUE, NOW(), 'pending', %s, %s, %s)
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
            criterion_db_id,
            test_run_id,
            auto_captured,
        ),
    )
    result = cur.fetchone()
    if not result:
        raise RuntimeError("Failed to create evidence record")
    return result[0], result[1], result[2]


# ============================================================
# Query functions
# ============================================================


def get_evidence(
    project_id: str,
    capability_id: str,
    criterion_id: str,
    version: int | None = None,
) -> dict[str, Any] | None:
    """Get evidence metadata (current version or specific version).

    Includes criterion_text via LEFT JOIN to acceptance_criteria if criterion_db_id is set.
    """
    with get_connection() as conn, conn.cursor() as cur:
        if version:
            cur.execute(
                f"SELECT {EVIDENCE_SELECT_WITH_CRITERION} FROM evidence e "
                "LEFT JOIN acceptance_criteria ac ON e.criterion_db_id = ac.id "
                "WHERE e.project_id = %s AND e.capability_id = %s AND e.criterion_id = %s AND e.version = %s",
                (project_id, capability_id, criterion_id, version),
            )
        else:
            cur.execute(
                f"SELECT {EVIDENCE_SELECT_WITH_CRITERION} FROM evidence e "
                "LEFT JOIN acceptance_criteria ac ON e.criterion_db_id = ac.id "
                "WHERE e.project_id = %s AND e.capability_id = %s AND e.criterion_id = %s AND e.is_current = TRUE",
                (project_id, capability_id, criterion_id),
            )
        row = cur.fetchone()

        if not row:
            return None

        return _row_to_evidence(row, include_criterion_text=True)


def get_latest_evidence(project_id: str) -> dict[str, Any] | None:
    """Get the most recently captured evidence for a project."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT {EVIDENCE_SELECT_COLUMNS} FROM evidence "
            "WHERE project_id = %s AND is_current = TRUE "
            "ORDER BY captured_at DESC LIMIT 1",
            (project_id,),
        )
        row = cur.fetchone()

        if not row:
            return None

        return _row_to_evidence(row)


def get_next_version(project_id: str, capability_id: str, criterion_id: str) -> int:
    """Get the next version number for a feature/criterion pair."""
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
            return int(row[0]) + 1
        return 1


def get_evidence_versions(
    project_id: str,
    capability_id: str,
    criterion_id: str,
) -> list[dict[str, Any]]:
    """Get all versions of evidence for a criterion."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT {EVIDENCE_SELECT_COLUMNS} FROM evidence "
            "WHERE project_id = %s AND capability_id = %s AND criterion_id = %s "
            "ORDER BY version DESC",
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
    criterion_db_id: int | None = None,
    test_run_id: int | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """List all current evidence for a project with filtering.

    Includes criterion_text via LEFT JOIN to acceptance_criteria.
    """
    with get_connection() as conn, conn.cursor() as cur:
        # Use table prefix for JOIN compatibility
        where_clauses = ["e.project_id = %s", "e.is_current = TRUE"]
        params: list[Any] = [project_id]

        if capability_id:
            where_clauses.append("e.capability_id = %s")
            params.append(capability_id)

        if quality_status:
            where_clauses.append("e.quality_status = %s")
            params.append(quality_status)

        if criterion_db_id:
            where_clauses.append("e.criterion_db_id = %s")
            params.append(criterion_db_id)

        if test_run_id:
            where_clauses.append("e.test_run_id = %s")
            params.append(test_run_id)

        if search:
            where_clauses.append(
                "(e.capability_id ILIKE %s OR e.criterion_id ILIKE %s OR e.evidence_id ILIKE %s)"
            )
            search_pattern = f"%{search}%"
            params.extend([search_pattern, search_pattern, search_pattern])

        # Build WHERE clause - clauses are safe literals defined in this function
        where_sql = sql.SQL(" AND ").join(sql.SQL(c) for c in where_clauses)

        # Get total count (no join needed for count)
        count_params = params.copy()
        cur.execute(
            sql.SQL("SELECT COUNT(*) FROM evidence e WHERE ") + where_sql,
            count_params,
        )
        count_row = cur.fetchone()
        total = int(count_row[0]) if count_row and count_row[0] else 0

        # Get paginated results with LEFT JOIN for criterion text
        params.extend([limit, offset])
        cur.execute(
            sql.SQL(f"SELECT {EVIDENCE_SELECT_WITH_CRITERION} FROM evidence e ")
            + sql.SQL("LEFT JOIN acceptance_criteria ac ON e.criterion_db_id = ac.id WHERE ")
            + where_sql
            + sql.SQL(" ORDER BY e.captured_at DESC LIMIT %s OFFSET %s"),
            params,
        )
        rows = cur.fetchall()

        return [_row_to_evidence(row, include_criterion_text=True) for row in rows], total


def _query_evidence_with_filter(
    project_id: str,
    where_clause: sql.SQL,
    order_clause: sql.SQL,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Internal helper to query evidence with specific filters."""
    with get_connection() as conn, conn.cursor() as cur:
        base_query = sql.SQL(
            "SELECT " + EVIDENCE_SELECT_COLUMNS + " FROM evidence "
            "WHERE project_id = %s AND {} AND is_current = TRUE "
            "ORDER BY {}"
        ).format(where_clause, order_clause)

        if limit is not None:
            query = sql.SQL("{} LIMIT %s").format(base_query)
            cur.execute(query, (project_id, limit))
        else:
            cur.execute(base_query, (project_id,))
        rows = cur.fetchall()
        return [_row_to_evidence(row) for row in rows]


def get_pending_review(project_id: str, limit: int = 50) -> list[dict[str, Any]]:
    """Get evidence pending AI review."""
    return _query_evidence_with_filter(
        project_id,
        sql.SQL("quality_status = 'pending'"),
        sql.SQL("captured_at DESC"),
        limit,
    )


def get_needs_user_review(project_id: str, limit: int = 50) -> list[dict[str, Any]]:
    """Get evidence that needs user review (low confidence or flagged)."""
    return _query_evidence_with_filter(
        project_id,
        sql.SQL("quality_status = 'needs_review'"),
        sql.SQL("captured_at DESC"),
        limit,
    )


def get_with_user_notes(project_id: str, limit: int = 50) -> list[dict[str, Any]]:
    """Get evidence that has user notes/feedback."""
    return _query_evidence_with_filter(
        project_id,
        sql.SQL("user_notes IS NOT NULL"),
        sql.SQL("user_reviewed_at DESC"),
        limit,
    )


def get_auto_captured_evidence(project_id: str, limit: int = 50) -> list[dict[str, Any]]:
    """Get evidence that was auto-captured on test pass."""
    return _query_evidence_with_filter(
        project_id,
        sql.SQL("auto_captured = TRUE"),
        sql.SQL("captured_at DESC"),
        limit,
    )


# ============================================================
# Update functions
# ============================================================


def update_ai_review(
    project_id: str,
    evidence_id: str,
    quality_status: str,
    confidence: float,
    ai_evidence: str | None = None,
    quality_issues: list[str] | None = None,
    reviewed_by: str = "claude",
) -> bool:
    """Record AI review result for evidence."""
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
        return result is not None


def update_user_review(
    project_id: str,
    evidence_id: str,
    approved: bool | None,
    notes: str | None = None,
) -> bool:
    """Record user review for evidence."""
    # Compute quality_status from user decision
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
        return result is not None


# ============================================================
# Cleanup functions
# ============================================================


def get_evidence_pairs_to_clean(
    cur: Any,
    project_id: str,
    capability_id: str | None = None,
) -> list[tuple[str, str]]:
    """Get all capability/criterion pairs that have evidence to potentially clean."""
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
    result: list[tuple[str, str]] = cur.fetchall()
    return result


def delete_old_versions_for_pair(
    cur: Any,
    project_id: str,
    feat_id: str,
    crit_id: str,
    max_versions: int,
    evidence_base: Path,
    dry_run: bool,
) -> tuple[int, int]:
    """Delete old versions for a single capability/criterion pair.

    Returns:
        Tuple of (deleted_count, deleted_size_bytes)
    """
    import shutil

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

    deleted_count = 0
    deleted_size = 0

    for row in old_versions:
        ev_id, _evidence_id, _file_path, size, version_val = row

        if not dry_run:
            version_str = str(version_val) if version_val is not None else "0"
            version_dir = evidence_base / str(feat_id) / str(crit_id) / f"v{version_str}"
            if version_dir.exists():
                shutil.rmtree(version_dir)
            cur.execute("DELETE FROM evidence WHERE id = %s", (ev_id,))

        deleted_count += 1
        if isinstance(size, int | float):
            deleted_size += int(size)

    return deleted_count, deleted_size


# ============================================================
# Aggregation functions
# ============================================================


def get_summary(project_id: str) -> dict[str, Any]:
    """Get summary statistics for evidence in a project."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                COUNT(*) FILTER (WHERE is_current = TRUE) as total_current,
                COUNT(*) FILTER (WHERE is_current = TRUE AND auto_captured = TRUE) as auto_captured_count,
                COUNT(*) FILTER (WHERE is_current = TRUE AND user_notes IS NOT NULL) as with_notes,
                COALESCE(SUM(file_size_bytes), 0) as total_size,
                COUNT(*) FILTER (WHERE is_current = TRUE AND quality_status = 'pending') as status_pending,
                COUNT(*) FILTER (WHERE is_current = TRUE AND quality_status = 'passed') as status_passed,
                COUNT(*) FILTER (WHERE is_current = TRUE AND quality_status = 'failed') as status_failed,
                COUNT(*) FILTER (WHERE is_current = TRUE AND quality_status = 'needs_review') as status_needs_review
            FROM evidence
            WHERE project_id = %s
            """,
            (project_id,),
        )
        row = cur.fetchone()

        if not row:
            return {
                "total_current": 0,
                "by_status": {},
                "auto_captured_count": 0,
                "with_user_notes": 0,
                "total_storage_bytes": 0,
            }

        by_status: dict[str, int] = {}
        if row[4]:
            by_status["pending"] = int(row[4])
        if row[5]:
            by_status["passed"] = int(row[5])
        if row[6]:
            by_status["failed"] = int(row[6])
        if row[7]:
            by_status["needs_review"] = int(row[7])

        return {
            "total_current": int(row[0]) if row[0] else 0,
            "by_status": by_status,
            "auto_captured_count": int(row[1]) if row[1] else 0,
            "with_user_notes": int(row[2]) if row[2] else 0,
            "total_storage_bytes": int(row[3]) if row[3] else 0,
        }


def get_evidence_count_for_criteria(
    project_id: str,
    criterion_ids: list[int],
) -> dict[int, int]:
    """Get evidence count for each criterion.

    Args:
        project_id: Project ID
        criterion_ids: List of criterion database IDs (acceptance_criteria.id)

    Returns:
        Dict mapping criterion_db_id to evidence count
    """
    if not criterion_ids:
        return {}

    with get_connection() as conn, conn.cursor() as cur:
        # Use ANY for efficient IN query
        cur.execute(
            """
            SELECT criterion_db_id, COUNT(*)
            FROM evidence
            WHERE project_id = %s AND criterion_db_id = ANY(%s) AND is_current = TRUE
            GROUP BY criterion_db_id
            """,
            (project_id, criterion_ids),
        )
        rows = cur.fetchall()

        return {row[0]: int(row[1]) for row in rows}


def get_test_evidence(
    project_id: str,
    test_id: str,
    test_run_id: int | None = None,
) -> list[dict[str, Any]]:
    """Get evidence for a test or test run."""
    capability_id = f"test-{test_id}"

    if test_run_id:
        criterion_id = f"run-{test_run_id}"
        return get_evidence_versions(project_id, capability_id, criterion_id)

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT {EVIDENCE_SELECT_COLUMNS} FROM evidence "
            "WHERE project_id = %s AND capability_id = %s AND is_current = TRUE "
            "ORDER BY captured_at DESC",
            (project_id, capability_id),
        )
        rows = cur.fetchall()

        return [_row_to_evidence(row) for row in rows]


def update_test_run_evidence_path(test_run_id: int, evidence_path: str) -> None:
    """Update test_runs with evidence_path."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE test_runs
            SET evidence_path = %s, updated_at = NOW()
            WHERE id = %s
            """,
            (evidence_path, test_run_id),
        )
        conn.commit()
