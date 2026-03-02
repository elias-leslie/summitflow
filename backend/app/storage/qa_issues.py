"""Storage module for QA issues.

Handles CRUD operations for the qa_issues table that tracks
code quality issues detected by Explorer scans.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from psycopg import Connection

from .connection import get_connection

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

STATUS_OPEN = "open"
STATUS_RESOLVED = "resolved"
SEVERITY_MEDIUM = "medium"
DEFAULT_RESOLUTION_REASON = "Issue no longer detected"

_SELECT_COLS = """
    id, project_id, issue_type, severity, file_path, entry_id,
    title, description, metadata, first_detected_at, last_detected_at,
    detected_in_scan_id, detection_count, status, resolved_at,
    resolution_scan_id, resolution_reason, st_task_id,
    created_at, updated_at
"""

# ---------------------------------------------------------------------------
# SQL statements
# ---------------------------------------------------------------------------

_SQL_GET_BY_ID = f"SELECT {_SELECT_COLS} FROM qa_issues WHERE id = %s"

_SQL_GET_OPEN_FOR_PROJECT = f"""
    SELECT {_SELECT_COLS}
    FROM qa_issues
    WHERE project_id = %s AND status = '{STATUS_OPEN}'
    ORDER BY last_detected_at DESC
"""

_SQL_GET_LINKED_TO_TASKS = f"""
    SELECT {_SELECT_COLS}
    FROM qa_issues
    WHERE project_id = %s AND st_task_id IS NOT NULL AND status = '{STATUS_OPEN}'
    ORDER BY last_detected_at DESC
"""

_SQL_MARK_RESOLVED = f"""
    UPDATE qa_issues
    SET status = '{STATUS_RESOLVED}',
        resolved_at = %s,
        resolution_scan_id = %s,
        resolution_reason = %s,
        updated_at = NOW()
    WHERE id = %s AND status = '{STATUS_OPEN}'
"""

_SQL_FIND_OPEN_ISSUE = f"""
    SELECT id FROM qa_issues
    WHERE project_id = %s AND issue_type = %s
      AND file_path IS NOT DISTINCT FROM %s
      AND status = '{STATUS_OPEN}'
    FOR UPDATE
"""

_SQL_UPDATE_ISSUE = """
    UPDATE qa_issues
    SET last_detected_at = %s,
        detected_in_scan_id = COALESCE(%s, detected_in_scan_id),
        detection_count = detection_count + 1,
        metadata = COALESCE(%s, metadata),
        updated_at = NOW()
    WHERE id = %s
    RETURNING id
"""

_SQL_INSERT_ISSUE = """
    INSERT INTO qa_issues (
        project_id, issue_type, severity, file_path, entry_id,
        title, description, metadata, first_detected_at, last_detected_at,
        detected_in_scan_id
    )
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    RETURNING id
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_issue(issue_id: int, conn: Connection | None = None) -> dict[str, Any] | None:
    """Get a QA issue by ID."""

    def _do(c: Connection) -> dict[str, Any] | None:
        with c.cursor() as cur:
            cur.execute(_SQL_GET_BY_ID, (issue_id,))
            row = cur.fetchone()
            return _row_to_dict(row) if row else None

    if conn:
        return _do(conn)
    with get_connection() as c:
        return _do(c)


def get_open_issues_for_project(
    project_id: str,
    conn: Connection | None = None,
) -> list[dict[str, Any]]:
    """Get all open issues for a project."""

    def _do(c: Connection) -> list[dict[str, Any]]:
        with c.cursor() as cur:
            cur.execute(_SQL_GET_OPEN_FOR_PROJECT, (project_id,))
            return [_row_to_dict(row) for row in cur.fetchall()]

    if conn:
        return _do(conn)
    with get_connection() as c:
        return _do(c)


def get_issues_linked_to_tasks(
    project_id: str,
    conn: Connection | None = None,
) -> list[dict[str, Any]]:
    """Get issues that are linked to SummitFlow tasks."""

    def _do(c: Connection) -> list[dict[str, Any]]:
        with c.cursor() as cur:
            cur.execute(_SQL_GET_LINKED_TO_TASKS, (project_id,))
            return [_row_to_dict(row) for row in cur.fetchall()]

    if conn:
        return _do(conn)
    with get_connection() as c:
        return _do(c)


def mark_issue_resolved(
    issue_id: int,
    scan_id: int | None = None,
    reason: str = DEFAULT_RESOLUTION_REASON,
    conn: Connection | None = None,
) -> bool:
    """Mark an issue as resolved.

    Returns:
        True if updated, False if not found
    """

    def _do(c: Connection) -> bool:
        with c.cursor() as cur:
            cur.execute(_SQL_MARK_RESOLVED, (datetime.now(UTC), scan_id, reason, issue_id))
            return bool(cur.rowcount > 0)

    if conn:
        return _do(conn)
    with get_connection() as c:
        result = _do(c)
        c.commit()
        return result


def upsert_issue(
    project_id: str,
    issue_type: str,
    file_path: str | None,
    title: str,
    severity: str = SEVERITY_MEDIUM,
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

    Returns:
        The issue ID
    """
    now = datetime.now(UTC)
    metadata_json = json.dumps(metadata) if metadata else None

    def _do(c: Connection) -> int:
        with c.cursor() as cur:
            cur.execute(_SQL_FIND_OPEN_ISSUE, (project_id, issue_type, file_path))
            row = cur.fetchone()
            if row:
                return _update_existing_issue(cur, row[0], now, scan_id, metadata_json)
            return _insert_new_issue(
                cur, project_id, issue_type, severity, file_path,
                entry_id, title, description, metadata_json, now, scan_id,
            )

    if conn:
        return _do(conn)
    with get_connection() as c:
        issue_id = _do(c)
        c.commit()
        return issue_id


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _update_existing_issue(
    cur: Any,
    issue_id: int,
    now: datetime,
    scan_id: int | None,
    metadata_json: str | None,
) -> int:
    """Update detection metadata on an existing open issue."""
    cur.execute(_SQL_UPDATE_ISSUE, (now, scan_id, metadata_json, issue_id))
    result = cur.fetchone()
    return int(result[0]) if result else int(issue_id)


def _insert_new_issue(
    cur: Any,
    project_id: str,
    issue_type: str,
    severity: str,
    file_path: str | None,
    entry_id: int | None,
    title: str,
    description: str | None,
    metadata_json: str | None,
    now: datetime,
    scan_id: int | None,
) -> int:
    """Insert a new QA issue row."""
    cur.execute(
        _SQL_INSERT_ISSUE,
        (
            project_id, issue_type, severity, file_path, entry_id,
            title, description, metadata_json, now, now, scan_id,
        ),
    )
    result = cur.fetchone()
    if not result:
        raise RuntimeError("Failed to insert issue")
    return int(result[0])


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
