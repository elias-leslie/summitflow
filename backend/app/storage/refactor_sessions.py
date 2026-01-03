"""Refactor session storage layer.

Persists refactor_it baseline scan IDs and session metadata.
Replaces volatile /tmp file storage with database persistence.
"""

from __future__ import annotations

import logging
from typing import Any

from .connection import get_connection

logger = logging.getLogger(__name__)


def create_refactor_session(
    project_id: str,
    task_id: str,
    baseline_scan_id: int | None = None,
    baseline_commit_sha: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any] | None:
    """Create a new refactor session.

    Args:
        project_id: Project ID
        task_id: SummitFlow task ID
        baseline_scan_id: Reference to scan_history entry
        baseline_commit_sha: Git commit SHA at baseline
        session_id: Claude session ID

    Returns:
        Created session dict or None if failed
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO refactor_sessions
                (project_id, task_id, baseline_scan_id, baseline_commit_sha, session_id)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (project_id, task_id) DO UPDATE SET
                baseline_scan_id = COALESCE(EXCLUDED.baseline_scan_id, refactor_sessions.baseline_scan_id),
                baseline_commit_sha = COALESCE(EXCLUDED.baseline_commit_sha, refactor_sessions.baseline_commit_sha),
                session_id = COALESCE(EXCLUDED.session_id, refactor_sessions.session_id)
            RETURNING id, project_id, task_id, baseline_scan_id, baseline_commit_sha,
                      status, session_id, final_scan_id, final_commit_sha,
                      subtasks_planned, subtasks_completed, started_at, completed_at
            """,
            (project_id, task_id, baseline_scan_id, baseline_commit_sha, session_id),
        )
        row = cur.fetchone()
        conn.commit()

    if row:
        return _row_to_dict(row)
    return None


def get_refactor_session(
    project_id: str,
    task_id: str,
) -> dict[str, Any] | None:
    """Get refactor session by project and task ID.

    Args:
        project_id: Project ID
        task_id: SummitFlow task ID

    Returns:
        Session dict or None if not found
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, project_id, task_id, baseline_scan_id, baseline_commit_sha,
                   status, session_id, final_scan_id, final_commit_sha,
                   subtasks_planned, subtasks_completed, started_at, completed_at
            FROM refactor_sessions
            WHERE project_id = %s AND task_id = %s
            """,
            (project_id, task_id),
        )
        row = cur.fetchone()

    if row:
        return _row_to_dict(row)
    return None


def get_active_refactor_session(
    project_id: str,
) -> dict[str, Any] | None:
    """Get the active refactor session for a project.

    Args:
        project_id: Project ID

    Returns:
        Session dict or None if no active session
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, project_id, task_id, baseline_scan_id, baseline_commit_sha,
                   status, session_id, final_scan_id, final_commit_sha,
                   subtasks_planned, subtasks_completed, started_at, completed_at
            FROM refactor_sessions
            WHERE project_id = %s AND status = 'active'
            ORDER BY started_at DESC
            LIMIT 1
            """,
            (project_id,),
        )
        row = cur.fetchone()

    if row:
        return _row_to_dict(row)
    return None


def update_refactor_session(
    project_id: str,
    task_id: str,
    **updates: Any,
) -> dict[str, Any] | None:
    """Update refactor session fields.

    Args:
        project_id: Project ID
        task_id: SummitFlow task ID
        **updates: Fields to update (status, final_scan_id, final_commit_sha,
                   subtasks_planned, subtasks_completed, completed_at)

    Returns:
        Updated session dict or None if not found
    """
    allowed_fields = {
        "status",
        "final_scan_id",
        "final_commit_sha",
        "subtasks_planned",
        "subtasks_completed",
        "completed_at",
        "baseline_scan_id",
        "baseline_commit_sha",
    }

    filtered = {k: v for k, v in updates.items() if k in allowed_fields}
    if not filtered:
        return get_refactor_session(project_id, task_id)

    set_clause = ", ".join(f"{k} = %s" for k in filtered)
    values = [*list(filtered.values()), project_id, task_id]

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE refactor_sessions
            SET {set_clause}
            WHERE project_id = %s AND task_id = %s
            RETURNING id, project_id, task_id, baseline_scan_id, baseline_commit_sha,
                      status, session_id, final_scan_id, final_commit_sha,
                      subtasks_planned, subtasks_completed, started_at, completed_at
            """,
            values,
        )
        row = cur.fetchone()
        conn.commit()

    if row:
        return _row_to_dict(row)
    return None


def complete_refactor_session(
    project_id: str,
    task_id: str,
    final_scan_id: int | None = None,
    final_commit_sha: str | None = None,
    status: str = "completed",
) -> dict[str, Any] | None:
    """Mark a refactor session as completed.

    Args:
        project_id: Project ID
        task_id: SummitFlow task ID
        final_scan_id: Final scan reference
        final_commit_sha: Final git commit SHA
        status: Final status (completed or abandoned)

    Returns:
        Updated session dict or None if not found
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE refactor_sessions
            SET status = %s,
                final_scan_id = %s,
                final_commit_sha = %s,
                completed_at = NOW()
            WHERE project_id = %s AND task_id = %s
            RETURNING id, project_id, task_id, baseline_scan_id, baseline_commit_sha,
                      status, session_id, final_scan_id, final_commit_sha,
                      subtasks_planned, subtasks_completed, started_at, completed_at
            """,
            (status, final_scan_id, final_commit_sha, project_id, task_id),
        )
        row = cur.fetchone()
        conn.commit()

    if row:
        return _row_to_dict(row)
    return None


def _row_to_dict(row: tuple[Any, ...]) -> dict[str, Any]:
    """Convert database row to dictionary."""
    return {
        "id": row[0],
        "project_id": row[1],
        "task_id": row[2],
        "baseline_scan_id": row[3],
        "baseline_commit_sha": row[4],
        "status": row[5],
        "session_id": row[6],
        "final_scan_id": row[7],
        "final_commit_sha": row[8],
        "subtasks_planned": row[9],
        "subtasks_completed": row[10],
        "started_at": row[11].isoformat() if row[11] else None,
        "completed_at": row[12].isoformat() if row[12] else None,
    }
