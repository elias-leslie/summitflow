"""Evidence Storage - Database operations for evidence management.

This module handles all database interactions for evidence records:
- CRUD operations for evidence
- Query filtering and pagination
- Review status updates
- Aggregation queries

Evidence is linked to tasks (task_id) and/or explorer entries (explorer_entry_id).
At least one must be present (enforced by CHECK constraint).
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from psycopg import sql

from .connection import get_connection

# Evidence type constants
EVIDENCE_TYPES = frozenset({"screenshot", "mockup", "test-output", "api-response", "console_error"})

# Mockup status constants
MOCKUP_STATUSES = frozenset({"generated", "pending_approval", "approved", "rejected"})


def generate_evidence_id() -> str:
    """Generate a new evidence ID in the format ev-{uuid}."""
    return f"ev-{uuid.uuid4().hex[:12]}"


# Base SELECT columns for evidence queries
EVIDENCE_SELECT_COLUMNS = """id, evidence_id, task_id, explorer_entry_id, evidence_type,
       file_path, file_size_bytes, version, is_current,
       captured_at, quality_status, quality_issues,
       confidence, ai_reviewed_at, ai_reviewed_by, ai_evidence,
       user_reviewed_at, user_approved, user_notes,
       criterion_db_id, test_run_id, auto_captured,
       linked_evidence_id, mockup_status, environment, viewport_name"""

# SELECT columns with LEFT JOIN to acceptance_criteria for criterion text
EVIDENCE_SELECT_WITH_CRITERION = """e.id, e.evidence_id, e.task_id, e.explorer_entry_id, e.evidence_type,
       e.file_path, e.file_size_bytes, e.version, e.is_current,
       e.captured_at, e.quality_status, e.quality_issues,
       e.confidence, e.ai_reviewed_at, e.ai_reviewed_by, e.ai_evidence,
       e.user_reviewed_at, e.user_approved, e.user_notes,
       e.criterion_db_id, e.test_run_id, e.auto_captured,
       e.linked_evidence_id, e.mockup_status, e.environment, e.viewport_name,
       ac.criterion as criterion_text"""


def _row_to_evidence(
    row: tuple[Any, ...], *, include_criterion_text: bool = False
) -> dict[str, Any]:
    """Convert database row to evidence dict.

    Args:
        row: Database row tuple
        include_criterion_text: If True, expects row[26] to contain criterion text from JOIN
    """
    result = {
        "id": row[0],
        "evidence_id": row[1],
        "task_id": row[2],
        "explorer_entry_id": row[3],
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
        "linked_evidence_id": row[22],
        "mockup_status": row[23],
        "environment": row[24],
        "viewport_name": row[25],
    }
    if include_criterion_text and len(row) > 26:
        result["criterion_text"] = row[26]
    return result


# ============================================================
# Internal helper functions (used within transactions)
# ============================================================


def mark_previous_as_stale(
    cur: Any,
    project_id: str,
    *,
    task_id: str | None = None,
    explorer_entry_id: int | None = None,
    evidence_type: str = "screenshot",
) -> None:
    """Mark previous evidence versions as not current.

    Must specify at least one of task_id or explorer_entry_id.
    """
    if task_id and explorer_entry_id:
        cur.execute(
            """
            UPDATE evidence
            SET is_current = FALSE, updated_at = NOW()
            WHERE project_id = %s AND task_id = %s AND explorer_entry_id = %s
              AND evidence_type = %s AND is_current = TRUE
            """,
            (project_id, task_id, explorer_entry_id, evidence_type),
        )
    elif task_id:
        cur.execute(
            """
            UPDATE evidence
            SET is_current = FALSE, updated_at = NOW()
            WHERE project_id = %s AND task_id = %s AND evidence_type = %s AND is_current = TRUE
            """,
            (project_id, task_id, evidence_type),
        )
    elif explorer_entry_id:
        cur.execute(
            """
            UPDATE evidence
            SET is_current = FALSE, updated_at = NOW()
            WHERE project_id = %s AND explorer_entry_id = %s AND evidence_type = %s AND is_current = TRUE
            """,
            (project_id, explorer_entry_id, evidence_type),
        )


def insert_evidence_record(
    cur: Any,
    project_id: str,
    file_path: str,
    file_size_bytes: int | None,
    *,
    task_id: str | None = None,
    explorer_entry_id: int | None = None,
    evidence_type: str = "screenshot",
    version: int = 1,
    criterion_db_id: int | None = None,
    test_run_id: int | None = None,
    auto_captured: bool = False,
    linked_evidence_id: int | None = None,
    mockup_status: str | None = None,
    environment: str = "local",
    viewport_name: str | None = None,
) -> tuple[int, str, datetime | None]:
    """Insert a new evidence record and return (id, evidence_id, captured_at).

    Args:
        cur: Database cursor
        project_id: Project ID
        file_path: Path to evidence file
        file_size_bytes: Size of evidence file
        task_id: Task ID (at least one of task_id or explorer_entry_id required)
        explorer_entry_id: Explorer entry ID
        evidence_type: Type of evidence (screenshot, mockup, test-output, api-response, console_error)
        version: Version number
        criterion_db_id: FK to acceptance_criteria.id (optional)
        test_run_id: FK to test_runs.id if captured during test run (optional)
        auto_captured: True if evidence was auto-captured on test pass
        linked_evidence_id: FK to evidence.id for mockup comparison
        mockup_status: Status for mockup evidence (generated, pending_approval, approved, rejected)
        environment: Environment (local, staging, production)
        viewport_name: Viewport name for multi-viewport captures
    """
    if not task_id and not explorer_entry_id:
        raise ValueError("At least one of task_id or explorer_entry_id is required")

    if evidence_type not in EVIDENCE_TYPES:
        raise ValueError(f"Invalid evidence_type: {evidence_type}. Must be one of {EVIDENCE_TYPES}")

    if mockup_status and mockup_status not in MOCKUP_STATUSES:
        raise ValueError(
            f"Invalid mockup_status: {mockup_status}. Must be one of {MOCKUP_STATUSES}"
        )

    evidence_id = generate_evidence_id()

    cur.execute(
        """
        INSERT INTO evidence (
            project_id, evidence_id, task_id, explorer_entry_id, evidence_type,
            file_path, file_size_bytes, version, is_current,
            captured_at, quality_status, criterion_db_id, test_run_id, auto_captured,
            linked_evidence_id, mockup_status, environment, viewport_name
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, TRUE, NOW(), 'pending', %s, %s, %s, %s, %s, %s, %s)
        RETURNING id, evidence_id, captured_at
        """,
        (
            project_id,
            evidence_id,
            task_id,
            explorer_entry_id,
            evidence_type,
            file_path,
            file_size_bytes,
            version,
            criterion_db_id,
            test_run_id,
            auto_captured,
            linked_evidence_id,
            mockup_status,
            environment,
            viewport_name,
        ),
    )
    result = cur.fetchone()
    if not result:
        raise RuntimeError("Failed to create evidence record")
    return result[0], result[1], result[2]


# ============================================================
# Query functions
# ============================================================


def get_evidence_by_id(
    project_id: str,
    evidence_id: str,
) -> dict[str, Any] | None:
    """Get evidence by evidence_id.

    Includes criterion_text via LEFT JOIN to acceptance_criteria if criterion_db_id is set.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT {EVIDENCE_SELECT_WITH_CRITERION} FROM evidence e "
            "LEFT JOIN acceptance_criteria ac ON e.criterion_db_id = ac.id "
            "WHERE e.project_id = %s AND e.evidence_id = %s",
            (project_id, evidence_id),
        )
        row = cur.fetchone()

        if not row:
            return None

        return _row_to_evidence(row, include_criterion_text=True)


def get_evidence_by_db_id(
    db_id: int,
) -> dict[str, Any] | None:
    """Get evidence by database ID (primary key).

    Used for following linked_evidence_id references.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT {EVIDENCE_SELECT_WITH_CRITERION} FROM evidence e "
            "LEFT JOIN acceptance_criteria ac ON e.criterion_db_id = ac.id "
            "WHERE e.id = %s",
            (db_id,),
        )
        row = cur.fetchone()

        if not row:
            return None

        return _row_to_evidence(row, include_criterion_text=True)


def get_evidence_for_task(
    project_id: str,
    task_id: str,
    evidence_type: str | None = None,
    current_only: bool = True,
) -> list[dict[str, Any]]:
    """Get all evidence for a task.

    Args:
        project_id: Project ID
        task_id: Task ID
        evidence_type: Filter by evidence type (optional)
        current_only: If True, only return current versions
    """
    with get_connection() as conn, conn.cursor() as cur:
        query = (
            f"SELECT {EVIDENCE_SELECT_WITH_CRITERION} FROM evidence e "
            "LEFT JOIN acceptance_criteria ac ON e.criterion_db_id = ac.id "
            "WHERE e.project_id = %s AND e.task_id = %s"
        )
        params: list[Any] = [project_id, task_id]

        if current_only:
            query += " AND e.is_current = TRUE"

        if evidence_type:
            query += " AND e.evidence_type = %s"
            params.append(evidence_type)

        query += " ORDER BY e.captured_at DESC"

        cur.execute(query, params)
        rows = cur.fetchall()

        return [_row_to_evidence(row, include_criterion_text=True) for row in rows]


def get_evidence_for_entry(
    project_id: str,
    explorer_entry_id: int,
    evidence_type: str | None = None,
    current_only: bool = True,
) -> list[dict[str, Any]]:
    """Get all evidence for an explorer entry.

    Args:
        project_id: Project ID
        explorer_entry_id: Explorer entry ID
        evidence_type: Filter by evidence type (optional)
        current_only: If True, only return current versions
    """
    with get_connection() as conn, conn.cursor() as cur:
        query = (
            f"SELECT {EVIDENCE_SELECT_WITH_CRITERION} FROM evidence e "
            "LEFT JOIN acceptance_criteria ac ON e.criterion_db_id = ac.id "
            "WHERE e.project_id = %s AND e.explorer_entry_id = %s"
        )
        params: list[Any] = [project_id, explorer_entry_id]

        if current_only:
            query += " AND e.is_current = TRUE"

        if evidence_type:
            query += " AND e.evidence_type = %s"
            params.append(evidence_type)

        query += " ORDER BY e.captured_at DESC"

        cur.execute(query, params)
        rows = cur.fetchall()

        return [_row_to_evidence(row, include_criterion_text=True) for row in rows]


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


def get_next_version(
    project_id: str,
    *,
    task_id: str | None = None,
    explorer_entry_id: int | None = None,
    evidence_type: str = "screenshot",
) -> int:
    """Get the next version number for a task/entry + evidence_type combination."""
    with get_connection() as conn, conn.cursor() as cur:
        if task_id and explorer_entry_id:
            cur.execute(
                """
                SELECT MAX(version) as max_version
                FROM evidence
                WHERE project_id = %s AND task_id = %s AND explorer_entry_id = %s AND evidence_type = %s
                """,
                (project_id, task_id, explorer_entry_id, evidence_type),
            )
        elif task_id:
            cur.execute(
                """
                SELECT MAX(version) as max_version
                FROM evidence
                WHERE project_id = %s AND task_id = %s AND evidence_type = %s
                """,
                (project_id, task_id, evidence_type),
            )
        elif explorer_entry_id:
            cur.execute(
                """
                SELECT MAX(version) as max_version
                FROM evidence
                WHERE project_id = %s AND explorer_entry_id = %s AND evidence_type = %s
                """,
                (project_id, explorer_entry_id, evidence_type),
            )
        else:
            return 1

        row = cur.fetchone()

        if row and row[0]:
            return int(row[0]) + 1
        return 1


def list_evidence(
    project_id: str,
    limit: int = 100,
    offset: int = 0,
    task_id: str | None = None,
    explorer_entry_id: int | None = None,
    evidence_type: str | None = None,
    quality_status: str | None = None,
    search: str | None = None,
    criterion_db_id: int | None = None,
    test_run_id: int | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """List all current evidence for a project with filtering.

    Includes criterion_text via LEFT JOIN to acceptance_criteria.
    """
    with get_connection() as conn, conn.cursor() as cur:
        where_clauses = ["e.project_id = %s", "e.is_current = TRUE"]
        params: list[Any] = [project_id]

        if task_id:
            where_clauses.append("e.task_id = %s")
            params.append(task_id)

        if explorer_entry_id:
            where_clauses.append("e.explorer_entry_id = %s")
            params.append(explorer_entry_id)

        if evidence_type:
            where_clauses.append("e.evidence_type = %s")
            params.append(evidence_type)

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
            where_clauses.append("(e.task_id ILIKE %s OR e.evidence_id ILIKE %s)")
            search_pattern = f"%{search}%"
            params.extend([search_pattern, search_pattern])

        where_sql = sql.SQL(" AND ").join(sql.SQL(c) for c in where_clauses)

        # Get total count
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


# ============================================================
# Mockup-specific query functions
# ============================================================


def get_mockups_for_entry(
    project_id: str,
    explorer_entry_id: int,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """Get all mockups for an explorer entry.

    Args:
        project_id: Project ID
        explorer_entry_id: Explorer entry ID
        status: Filter by mockup_status (optional)
    """
    with get_connection() as conn, conn.cursor() as cur:
        query = (
            f"SELECT {EVIDENCE_SELECT_WITH_CRITERION} FROM evidence e "
            "LEFT JOIN acceptance_criteria ac ON e.criterion_db_id = ac.id "
            "WHERE e.project_id = %s AND e.explorer_entry_id = %s "
            "AND e.evidence_type = 'mockup' AND e.is_current = TRUE"
        )
        params: list[Any] = [project_id, explorer_entry_id]

        if status:
            query += " AND e.mockup_status = %s"
            params.append(status)

        query += " ORDER BY e.captured_at DESC"

        cur.execute(query, params)
        rows = cur.fetchall()

        return [_row_to_evidence(row, include_criterion_text=True) for row in rows]


def get_approved_mockup(
    project_id: str,
    explorer_entry_id: int,
) -> dict[str, Any] | None:
    """Get the approved mockup for an explorer entry (if any)."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT {EVIDENCE_SELECT_WITH_CRITERION} FROM evidence e "
            "LEFT JOIN acceptance_criteria ac ON e.criterion_db_id = ac.id "
            "WHERE e.project_id = %s AND e.explorer_entry_id = %s "
            "AND e.evidence_type = 'mockup' AND e.mockup_status = 'approved' "
            "AND e.is_current = TRUE "
            "ORDER BY e.captured_at DESC LIMIT 1",
            (project_id, explorer_entry_id),
        )
        row = cur.fetchone()

        if not row:
            return None

        return _row_to_evidence(row, include_criterion_text=True)


def update_mockup_status(
    project_id: str,
    evidence_id: str,
    status: str,
) -> bool:
    """Update the mockup_status of an evidence record.

    Args:
        project_id: Project ID
        evidence_id: Evidence ID
        status: New status (generated, pending_approval, approved, rejected)
    """
    if status not in MOCKUP_STATUSES:
        raise ValueError(f"Invalid mockup_status: {status}. Must be one of {MOCKUP_STATUSES}")

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE evidence
            SET mockup_status = %s, updated_at = NOW()
            WHERE project_id = %s AND evidence_id = %s AND evidence_type = 'mockup'
            RETURNING id
            """,
            (status, project_id, evidence_id),
        )
        result = cur.fetchone()
        conn.commit()
        return result is not None


# ============================================================
# Review filter functions
# ============================================================


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
                COUNT(*) FILTER (WHERE is_current = TRUE AND quality_status = 'needs_review') as status_needs_review,
                COUNT(*) FILTER (WHERE is_current = TRUE AND evidence_type = 'mockup') as mockup_count
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
                "mockup_count": 0,
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
            "mockup_count": int(row[8]) if row[8] else 0,
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


def update_test_run_evidence_path(test_run_id: int, evidence_path: str) -> None:
    """Update test_runs with evidence_path."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE test_runs
            SET evidence_path = %s
            WHERE id = %s
            """,
            (evidence_path, test_run_id),
        )
        conn.commit()
