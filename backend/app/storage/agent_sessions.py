"""Agent sessions storage layer - Build session tracking.

This module provides data access for agent build session tracking.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from psycopg import sql

from .connection import generate_prefixed_id, get_connection


def _generate_session_id() -> str:
    """Generate a unique session ID."""
    return generate_prefixed_id("sess")


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
    from psycopg.types.json import Jsonb

    session_id = _generate_session_id()
    build_state_json = Jsonb(build_state) if build_state else Jsonb({})

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO agent_sessions (project_id, session_id, agent_type, build_state)
            VALUES (%s, %s, %s, %s)
            RETURNING id, project_id, session_id, agent_type, status, started_at, ended_at,
                      capabilities_attempted, capabilities_passed, capabilities_failed,
                      tests_run, tests_passed, tests_failed, notes, git_commit_sha,
                      created_at, updated_at, build_state
            """,
            (project_id, session_id, agent_type, build_state_json),
        )
        row = cur.fetchone()
        conn.commit()

    return _row_to_dict(row)


def get_session(project_id: str, session_id: str) -> dict[str, Any] | None:
    """Get a session by project_id and session_id.

    Returns:
        Session dict or None if not found.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, project_id, session_id, agent_type, status, started_at, ended_at,
                   capabilities_attempted, capabilities_passed, capabilities_failed,
                   tests_run, tests_passed, tests_failed, notes, git_commit_sha,
                   created_at, updated_at, build_state
            FROM agent_sessions
            WHERE project_id = %s AND session_id = %s
            """,
            (project_id, session_id),
        )
        row = cur.fetchone()

    return _row_to_dict(row) if row else None


def get_session_by_id(session_db_id: int) -> dict[str, Any] | None:
    """Get a session by database ID.

    Returns:
        Session dict or None if not found.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, project_id, session_id, agent_type, status, started_at, ended_at,
                   capabilities_attempted, capabilities_passed, capabilities_failed,
                   tests_run, tests_passed, tests_failed, notes, git_commit_sha,
                   created_at, updated_at
            FROM agent_sessions
            WHERE id = %s
            """,
            (session_db_id,),
        )
        row = cur.fetchone()

    return _row_to_dict(row) if row else None


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
            """
            SELECT id, project_id, session_id, agent_type, status, started_at, ended_at,
                   capabilities_attempted, capabilities_passed, capabilities_failed,
                   tests_run, tests_passed, tests_failed, notes, git_commit_sha,
                   created_at, updated_at
            FROM agent_sessions
            WHERE project_id = %s
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (project_id, limit),
        )
        rows = cur.fetchall()

    return [_row_to_dict(row) for row in rows]


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
                """
                SELECT id, project_id, session_id, agent_type, status, started_at, ended_at,
                       capabilities_attempted, capabilities_passed, capabilities_failed,
                       tests_run, tests_passed, tests_failed, notes, git_commit_sha,
                       created_at, updated_at
                FROM agent_sessions
                WHERE project_id = %s AND status = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (project_id, status, limit),
            )
        else:
            cur.execute(
                """
                SELECT id, project_id, session_id, agent_type, status, started_at, ended_at,
                       capabilities_attempted, capabilities_passed, capabilities_failed,
                       tests_run, tests_passed, tests_failed, notes, git_commit_sha,
                       created_at, updated_at
                FROM agent_sessions
                WHERE project_id = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (project_id, limit),
            )
        rows = cur.fetchall()

    return [_row_to_dict(row) for row in rows]


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

    # Always update updated_at
    updates["updated_at"] = datetime.now(UTC)

    set_clauses = [sql.SQL("{} = %s").format(sql.Identifier(k)) for k in updates]
    values = [*list(updates.values()), project_id, session_id]

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            sql.SQL("""
            UPDATE agent_sessions
            SET {set_clause}
            WHERE project_id = %s AND session_id = %s
            RETURNING id, project_id, session_id, agent_type, status, started_at, ended_at,
                      capabilities_attempted, capabilities_passed, capabilities_failed,
                      tests_run, tests_passed, tests_failed, notes, git_commit_sha,
                      created_at, updated_at
            """).format(set_clause=sql.SQL(", ").join(set_clauses)),
            values,
        )
        row = cur.fetchone()
        conn.commit()

    return _row_to_dict(row) if row else None


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
            """
            UPDATE agent_sessions
            SET ended_at = %s, status = 'completed', notes = %s, git_commit_sha = %s, updated_at = %s
            WHERE project_id = %s AND session_id = %s
            RETURNING id, project_id, session_id, agent_type, status, started_at, ended_at,
                      capabilities_attempted, capabilities_passed, capabilities_failed,
                      tests_run, tests_passed, tests_failed, notes, git_commit_sha,
                      created_at, updated_at
            """,
            (now, notes, git_commit_sha, now, project_id, session_id),
        )
        row = cur.fetchone()
        conn.commit()

    return _row_to_dict(row) if row else None


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
            """
            UPDATE agent_sessions
            SET ended_at = %s, status = 'failed', notes = %s, updated_at = %s
            WHERE project_id = %s AND session_id = %s
            RETURNING id, project_id, session_id, agent_type, status, started_at, ended_at,
                      capabilities_attempted, capabilities_passed, capabilities_failed,
                      tests_run, tests_passed, tests_failed, notes, git_commit_sha,
                      created_at, updated_at
            """,
            (now, notes, now, project_id, session_id),
        )
        row = cur.fetchone()
        conn.commit()

    return _row_to_dict(row) if row else None


def add_capability_attempted(
    project_id: str,
    session_id: str,
    capability_id: str,
) -> dict[str, Any] | None:
    """Add a capability to the attempted list.

    Args:
        project_id: Project ID
        session_id: Session ID
        capability_id: Capability ID to add

    Returns:
        Updated session dict or None if not found.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE agent_sessions
            SET capabilities_attempted = array_append(capabilities_attempted, %s),
                updated_at = %s
            WHERE project_id = %s AND session_id = %s
            AND NOT (%s = ANY(capabilities_attempted))
            RETURNING id, project_id, session_id, agent_type, status, started_at, ended_at,
                      capabilities_attempted, capabilities_passed, capabilities_failed,
                      tests_run, tests_passed, tests_failed, notes, git_commit_sha,
                      created_at, updated_at
            """,
            (capability_id, datetime.now(UTC), project_id, session_id, capability_id),
        )
        row = cur.fetchone()
        conn.commit()

    if row:
        return _row_to_dict(row)
    # Return current state if no update (already in list)
    return get_session(project_id, session_id)


def mark_capability_passed(
    project_id: str,
    session_id: str,
    capability_id: str,
) -> dict[str, Any] | None:
    """Mark a capability as passed in this session.

    Args:
        project_id: Project ID
        session_id: Session ID
        capability_id: Capability ID

    Returns:
        Updated session dict or None if not found.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE agent_sessions
            SET capabilities_passed = array_append(capabilities_passed, %s),
                updated_at = %s
            WHERE project_id = %s AND session_id = %s
            AND NOT (%s = ANY(capabilities_passed))
            RETURNING id, project_id, session_id, agent_type, status, started_at, ended_at,
                      capabilities_attempted, capabilities_passed, capabilities_failed,
                      tests_run, tests_passed, tests_failed, notes, git_commit_sha,
                      created_at, updated_at
            """,
            (capability_id, datetime.now(UTC), project_id, session_id, capability_id),
        )
        row = cur.fetchone()
        conn.commit()

    if row:
        return _row_to_dict(row)
    return get_session(project_id, session_id)


def mark_capability_failed(
    project_id: str,
    session_id: str,
    capability_id: str,
) -> dict[str, Any] | None:
    """Mark a capability as failed in this session.

    Args:
        project_id: Project ID
        session_id: Session ID
        capability_id: Capability ID

    Returns:
        Updated session dict or None if not found.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE agent_sessions
            SET capabilities_failed = array_append(capabilities_failed, %s),
                updated_at = %s
            WHERE project_id = %s AND session_id = %s
            AND NOT (%s = ANY(capabilities_failed))
            RETURNING id, project_id, session_id, agent_type, status, started_at, ended_at,
                      capabilities_attempted, capabilities_passed, capabilities_failed,
                      tests_run, tests_passed, tests_failed, notes, git_commit_sha,
                      created_at, updated_at
            """,
            (capability_id, datetime.now(UTC), project_id, session_id, capability_id),
        )
        row = cur.fetchone()
        conn.commit()

    if row:
        return _row_to_dict(row)
    return get_session(project_id, session_id)


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
            """
            UPDATE agent_sessions
            SET tests_run = tests_run + %s,
                tests_passed = tests_passed + %s,
                tests_failed = tests_failed + %s,
                updated_at = %s
            WHERE project_id = %s AND session_id = %s
            RETURNING id, project_id, session_id, agent_type, status, started_at, ended_at,
                      capabilities_attempted, capabilities_passed, capabilities_failed,
                      tests_run, tests_passed, tests_failed, notes, git_commit_sha,
                      created_at, updated_at
            """,
            (total, passed, failed, datetime.now(UTC), project_id, session_id),
        )
        row = cur.fetchone()
        conn.commit()

    return _row_to_dict(row) if row else None


def get_build_state(
    project_id: str,
    session_id: str,
) -> dict[str, Any]:
    """Get the build state for a session.

    Args:
        project_id: Project ID
        session_id: Session ID

    Returns:
        Build state dict (empty dict if not set).
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT build_state
            FROM agent_sessions
            WHERE project_id = %s AND session_id = %s
            """,
            (project_id, session_id),
        )
        row = cur.fetchone()

    if row and row[0]:
        return dict(row[0])
    return {}


def update_build_state(
    project_id: str,
    session_id: str,
    build_state: dict[str, Any],
) -> dict[str, Any] | None:
    """Update the build state for a session.

    Args:
        project_id: Project ID
        session_id: Session ID
        build_state: Build state dict to store

    Returns:
        Updated build state or None if session not found.
    """
    import json

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE agent_sessions
            SET build_state = %s, updated_at = %s
            WHERE project_id = %s AND session_id = %s
            RETURNING build_state
            """,
            (json.dumps(build_state), datetime.now(UTC), project_id, session_id),
        )
        row = cur.fetchone()
        conn.commit()

    return row[0] if row else None


def merge_build_state(
    project_id: str,
    session_id: str,
    updates: dict[str, Any],
) -> dict[str, Any] | None:
    """Merge updates into existing build state.

    Args:
        project_id: Project ID
        session_id: Session ID
        updates: Dict of updates to merge

    Returns:
        Updated build state or None if session not found.
    """
    import json

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE agent_sessions
            SET build_state = build_state || %s, updated_at = %s
            WHERE project_id = %s AND session_id = %s
            RETURNING build_state
            """,
            (json.dumps(updates), datetime.now(UTC), project_id, session_id),
        )
        row = cur.fetchone()
        conn.commit()

    return row[0] if row else None


def _row_to_dict(row: tuple[Any, ...] | None) -> dict[str, Any]:
    """Convert a database row to a dict."""
    if row is None:
        return {}

    result = {
        "id": row[0],
        "project_id": row[1],
        "session_id": row[2],
        "agent_type": row[3],
        "status": row[4],
        "started_at": row[5].isoformat() if row[5] else None,
        "ended_at": row[6].isoformat() if row[6] else None,
        "capabilities_attempted": list(row[7]) if row[7] else [],
        "capabilities_passed": list(row[8]) if row[8] else [],
        "capabilities_failed": list(row[9]) if row[9] else [],
        "tests_run": row[10],
        "tests_passed": row[11],
        "tests_failed": row[12],
        "notes": row[13],
        "git_commit_sha": row[14],
        "created_at": row[15].isoformat() if row[15] else None,
        "updated_at": row[16].isoformat() if row[16] else None,
    }

    # Include build_state if present in query result
    if len(row) > 17:
        result["build_state"] = row[17] if row[17] else {}

    return result
