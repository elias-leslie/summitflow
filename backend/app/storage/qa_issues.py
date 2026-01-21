"""Storage module for QA issues.

Handles CRUD operations for the qa_issues table that tracks
code quality issues detected by Explorer scans.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from psycopg import Connection

from .connection import get_connection


def get_issue(issue_id: int, conn: Connection | None = None) -> dict[str, Any] | None:
    """Get a QA issue by ID.

    Args:
        issue_id: The issue ID
        conn: Optional database connection

    Returns:
        Issue dict or None if not found
    """
    query = """
        SELECT id, project_id, issue_type, severity, file_path, entry_id,
               title, description, metadata, first_detected_at, last_detected_at,
               detected_in_scan_id, detection_count, status, resolved_at,
               resolution_scan_id, resolution_reason, st_task_id,
               created_at, updated_at
        FROM qa_issues
        WHERE id = %s
    """

    def _do_get(c: Connection) -> dict[str, Any] | None:
        with c.cursor() as cur:
            cur.execute(query, (issue_id,))
            row = cur.fetchone()
            if not row:
                return None
            return _row_to_dict(row)

    if conn:
        return _do_get(conn)
    with get_connection() as c:
        return _do_get(c)


def get_open_issues_for_project(
    project_id: str,
    conn: Connection | None = None,
) -> list[dict[str, Any]]:
    """Get all open issues for a project.

    Args:
        project_id: Project ID
        conn: Optional database connection

    Returns:
        List of issue dicts
    """
    query = """
        SELECT id, project_id, issue_type, severity, file_path, entry_id,
               title, description, metadata, first_detected_at, last_detected_at,
               detected_in_scan_id, detection_count, status, resolved_at,
               resolution_scan_id, resolution_reason, st_task_id,
               created_at, updated_at
        FROM qa_issues
        WHERE project_id = %s AND status = 'open'
        ORDER BY last_detected_at DESC
    """

    def _do_get(c: Connection) -> list[dict[str, Any]]:
        with c.cursor() as cur:
            cur.execute(query, (project_id,))
            return [_row_to_dict(row) for row in cur.fetchall()]

    if conn:
        return _do_get(conn)
    with get_connection() as c:
        return _do_get(c)


def get_issues_linked_to_tasks(
    project_id: str,
    conn: Connection | None = None,
) -> list[dict[str, Any]]:
    """Get issues that are linked to SummitFlow tasks.

    Args:
        project_id: Project ID
        conn: Optional database connection

    Returns:
        List of issue dicts with st_task_id set
    """
    query = """
        SELECT id, project_id, issue_type, severity, file_path, entry_id,
               title, description, metadata, first_detected_at, last_detected_at,
               detected_in_scan_id, detection_count, status, resolved_at,
               resolution_scan_id, resolution_reason, st_task_id,
               created_at, updated_at
        FROM qa_issues
        WHERE project_id = %s AND st_task_id IS NOT NULL AND status = 'open'
        ORDER BY last_detected_at DESC
    """

    def _do_get(c: Connection) -> list[dict[str, Any]]:
        with c.cursor() as cur:
            cur.execute(query, (project_id,))
            return [_row_to_dict(row) for row in cur.fetchall()]

    if conn:
        return _do_get(conn)
    with get_connection() as c:
        return _do_get(c)


def mark_issue_resolved(
    issue_id: int,
    scan_id: int | None = None,
    reason: str = "Issue no longer detected",
    conn: Connection | None = None,
) -> bool:
    """Mark an issue as resolved.

    Args:
        issue_id: The issue ID
        scan_id: Optional scan ID that resolved the issue
        reason: Resolution reason
        conn: Optional database connection

    Returns:
        True if updated, False if not found
    """
    query = """
        UPDATE qa_issues
        SET status = 'resolved',
            resolved_at = %s,
            resolution_scan_id = %s,
            resolution_reason = %s,
            updated_at = NOW()
        WHERE id = %s AND status = 'open'
    """

    def _do_update(c: Connection) -> bool:
        with c.cursor() as cur:
            cur.execute(query, (datetime.now(UTC), scan_id, reason, issue_id))
            return bool(cur.rowcount > 0)

    if conn:
        return _do_update(conn)
    with get_connection() as c:
        result = _do_update(c)
        c.commit()
        return result


def upsert_issue(
    project_id: str,
    issue_type: str,
    file_path: str | None,
    title: str,
    severity: str = "medium",
    description: str | None = None,
    metadata: dict[str, Any] | None = None,
    entry_id: int | None = None,
    scan_id: int | None = None,
    conn: Connection | None = None,
) -> int:
    """Create or update a QA issue.

    If an issue with the same project/type/file exists and is open,
    updates its last_detected_at and increments detection_count.
    Otherwise creates a new issue.

    Args:
        project_id: Project ID
        issue_type: Type of issue (complexity, stale_file, etc.)
        file_path: File path or None for non-file issues
        title: Issue title
        severity: Severity level
        description: Optional description
        metadata: Optional metadata dict
        entry_id: Optional explorer entry ID
        scan_id: Optional scan ID
        conn: Optional database connection

    Returns:
        The issue ID
    """
    now = datetime.now(UTC)

    # Try to find existing open issue
    # Use IS NOT DISTINCT FROM for proper NULL handling
    find_query = """
        SELECT id FROM qa_issues
        WHERE project_id = %s AND issue_type = %s
          AND file_path IS NOT DISTINCT FROM %s
          AND status = 'open'
        FOR UPDATE
    """

    update_query = """
        UPDATE qa_issues
        SET last_detected_at = %s,
            detected_in_scan_id = COALESCE(%s, detected_in_scan_id),
            detection_count = detection_count + 1,
            metadata = COALESCE(%s, metadata),
            updated_at = NOW()
        WHERE id = %s
        RETURNING id
    """

    insert_query = """
        INSERT INTO qa_issues (
            project_id, issue_type, severity, file_path, entry_id,
            title, description, metadata, first_detected_at, last_detected_at,
            detected_in_scan_id
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
    """

    import json

    metadata_json = json.dumps(metadata) if metadata else None

    def _do_upsert(c: Connection) -> int:
        with c.cursor() as cur:
            # Check for existing issue
            cur.execute(find_query, (project_id, issue_type, file_path))
            row = cur.fetchone()

            if row:
                # Update existing
                cur.execute(update_query, (now, scan_id, metadata_json, row[0]))
                result = cur.fetchone()
                return int(result[0]) if result else int(row[0])
            else:
                # Insert new
                cur.execute(
                    insert_query,
                    (
                        project_id,
                        issue_type,
                        severity,
                        file_path,
                        entry_id,
                        title,
                        description,
                        metadata_json,
                        now,
                        now,
                        scan_id,
                    ),
                )
                result = cur.fetchone()
                if not result:
                    raise RuntimeError("Failed to insert issue")
                return int(result[0])

    if conn:
        return _do_upsert(conn)
    with get_connection() as c:
        issue_id = _do_upsert(c)
        c.commit()
        return issue_id


def _row_to_dict(row: tuple[Any, ...]) -> dict[str, Any]:
    """Convert database row to dict."""
    return {
        "id": row[0],
        "project_id": row[1],
        "issue_type": row[2],
        "severity": row[3],
        "file_path": row[4],
        "entry_id": row[5],
        "title": row[6],
        "description": row[7],
        "metadata": row[8],
        "first_detected_at": row[9],
        "last_detected_at": row[10],
        "detected_in_scan_id": row[11],
        "detection_count": row[12],
        "status": row[13],
        "resolved_at": row[14],
        "resolution_scan_id": row[15],
        "resolution_reason": row[16],
        "st_task_id": row[17],
        "created_at": row[18],
        "updated_at": row[19],
    }
