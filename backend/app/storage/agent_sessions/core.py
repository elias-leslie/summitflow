"""Core CRUD operations for agent sessions."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from psycopg import sql
from psycopg.types.json import Jsonb

from ..connection import generate_prefixed_id, get_connection
from ._fields import SESSION_FIELDS, SESSION_FIELDS_WITH_STATE, row_to_dict


def create_session(
    project_id: str,
    agent_type: str,
    build_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a new agent build session.

    Args:
        project_id: Project ID
        agent_type: Type of agent ('claude', 'gemini', 'human')
        build_state: Optional initial build state for implementation sessions

    Returns:
        The created session dict.
    """
    session_id = generate_prefixed_id("sess")
    build_state_json = Jsonb(build_state) if build_state else Jsonb({})

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO agent_sessions (project_id, session_id, agent_type, build_state)
            VALUES (%s, %s, %s, %s)
            RETURNING {SESSION_FIELDS_WITH_STATE}
            """,
            (project_id, session_id, agent_type, build_state_json),
        )
        row = cur.fetchone()
        conn.commit()

    return row_to_dict(row, include_build_state=True)


def get_session(project_id: str, session_id: str) -> dict[str, Any] | None:
    """Get a session by project_id and session_id.

    Returns:
        Session dict or None if not found.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {SESSION_FIELDS_WITH_STATE}
            FROM agent_sessions
            WHERE project_id = %s AND session_id = %s
            """,
            (project_id, session_id),
        )
        row = cur.fetchone()

    return row_to_dict(row, include_build_state=True) if row else None


def get_session_by_id(session_db_id: int) -> dict[str, Any] | None:
    """Get a session by database ID.

    Returns:
        Session dict or None if not found.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {SESSION_FIELDS}
            FROM agent_sessions
            WHERE id = %s
            """,
            (session_db_id,),
        )
        row = cur.fetchone()

    return row_to_dict(row) if row else None


def get_recent_sessions(
    project_id: str,
    limit: int = 3,
) -> list[dict[str, Any]]:
    """Get recent sessions for a project.

    Args:
        project_id: Project ID
        limit: Maximum number of sessions to return (default 3)

    Returns:
        List of session dicts, ordered by created_at DESC.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {SESSION_FIELDS}
            FROM agent_sessions
            WHERE project_id = %s
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (project_id, limit),
        )
        rows = cur.fetchall()

    return [row_to_dict(row) for row in rows]


def list_sessions(
    project_id: str,
    status: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """List sessions for a project, optionally filtered by status.

    Args:
        project_id: Project ID
        status: Optional status to filter by ('running', 'completed', 'failed')
        limit: Maximum number of sessions to return

    Returns:
        List of session dicts, ordered by created_at DESC.
    """
    with get_connection() as conn, conn.cursor() as cur:
        if status is not None:
            cur.execute(
                f"""
                SELECT {SESSION_FIELDS}
                FROM agent_sessions
                WHERE project_id = %s AND status = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (project_id, status, limit),
            )
        else:
            cur.execute(
                f"""
                SELECT {SESSION_FIELDS}
                FROM agent_sessions
                WHERE project_id = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (project_id, limit),
            )
        rows = cur.fetchall()

    return [row_to_dict(row) for row in rows]


def update_session(
    project_id: str,
    session_id: str,
    **kwargs: Any,
) -> dict[str, Any] | None:
    """Update a session.

    Args:
        project_id: Project ID
        session_id: Session ID
        **kwargs: Fields to update (status, capabilities_attempted, capabilities_passed,
                  capabilities_failed, tests_run, tests_passed, tests_failed, notes)

    Returns:
        Updated session dict or None if not found.
    """
    allowed_fields = {
        "status",
        "capabilities_attempted",
        "capabilities_passed",
        "capabilities_failed",
        "tests_run",
        "tests_passed",
        "tests_failed",
        "notes",
    }
    updates = {k: v for k, v in kwargs.items() if k in allowed_fields}

    if not updates:
        return get_session(project_id, session_id)

    updates["updated_at"] = datetime.now(UTC)

    set_clauses = [sql.SQL("{} = %s").format(sql.Identifier(k)) for k in updates]
    values = [*list(updates.values()), project_id, session_id]

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            sql.SQL(f"""
            UPDATE agent_sessions
            SET {{set_clause}}
            WHERE project_id = %s AND session_id = %s
            RETURNING {SESSION_FIELDS}
            """).format(set_clause=sql.SQL(", ").join(set_clauses)),
            values,
        )
        row = cur.fetchone()
        conn.commit()

    return row_to_dict(row) if row else None


def end_session(
    project_id: str,
    session_id: str,
    notes: str | None = None,
    git_commit_sha: str | None = None,
) -> dict[str, Any] | None:
    """End a session (mark as completed).

    Sets ended_at timestamp and status to 'completed'.

    Args:
        project_id: Project ID
        session_id: Session ID
        notes: Handoff notes for the next agent
        git_commit_sha: Git commit SHA at end of session

    Returns:
        Updated session dict or None if not found.
    """
    now = datetime.now(UTC)

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE agent_sessions
            SET ended_at = %s, status = 'completed', notes = %s, git_commit_sha = %s, updated_at = %s
            WHERE project_id = %s AND session_id = %s
            RETURNING {SESSION_FIELDS}
            """,
            (now, notes, git_commit_sha, now, project_id, session_id),
        )
        row = cur.fetchone()
        conn.commit()

    return row_to_dict(row) if row else None


def fail_session(
    project_id: str,
    session_id: str,
    notes: str | None = None,
) -> dict[str, Any] | None:
    """Mark a session as failed.

    Sets ended_at timestamp and status to 'failed'.

    Args:
        project_id: Project ID
        session_id: Session ID
        notes: Error notes

    Returns:
        Updated session dict or None if not found.
    """
    now = datetime.now(UTC)

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE agent_sessions
            SET ended_at = %s, status = 'failed', notes = %s, updated_at = %s
            WHERE project_id = %s AND session_id = %s
            RETURNING {SESSION_FIELDS}
            """,
            (now, notes, now, project_id, session_id),
        )
        row = cur.fetchone()
        conn.commit()

    return row_to_dict(row) if row else None


def increment_test_counts(
    project_id: str,
    session_id: str,
    passed: int = 0,
    failed: int = 0,
) -> dict[str, Any] | None:
    """Increment test run counts for a session.

    Args:
        project_id: Project ID
        session_id: Session ID
        passed: Number of tests passed
        failed: Number of tests failed

    Returns:
        Updated session dict or None if not found.
    """
    total = passed + failed
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE agent_sessions
            SET tests_run = tests_run + %s,
                tests_passed = tests_passed + %s,
                tests_failed = tests_failed + %s,
                updated_at = %s
            WHERE project_id = %s AND session_id = %s
            RETURNING {SESSION_FIELDS}
            """,
            (total, passed, failed, datetime.now(UTC), project_id, session_id),
        )
        row = cur.fetchone()
        conn.commit()

    return row_to_dict(row) if row else None
