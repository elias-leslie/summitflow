"""Terminal sessions storage layer - Session CRUD and lifecycle management.

This module provides data access for terminal session persistence.
Sessions represent persistent tmux terminals that survive browser close.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

import psycopg.sql

from .connection import get_connection


def list_sessions(
    user_id: str | None = None,
    include_dead: bool = False,
) -> list[dict[str, Any]]:
    """List terminal sessions.

    Args:
        user_id: Optional user ID filter (for future auth support)
        include_dead: Include sessions marked as dead (default False)

    Returns:
        List of session dicts ordered by display_order
    """
    with get_connection() as conn, conn.cursor() as cur:
        if user_id:
            if include_dead:
                cur.execute(
                    """
                    SELECT id, name, user_id, project_id, working_dir, display_order,
                           is_alive, created_at, last_accessed_at
                    FROM terminal_sessions
                    WHERE user_id = %s
                    ORDER BY display_order, created_at
                    """,
                    (user_id,),
                )
            else:
                cur.execute(
                    """
                    SELECT id, name, user_id, project_id, working_dir, display_order,
                           is_alive, created_at, last_accessed_at
                    FROM terminal_sessions
                    WHERE user_id = %s AND is_alive = true
                    ORDER BY display_order, created_at
                    """,
                    (user_id,),
                )
        else:
            if include_dead:
                cur.execute(
                    """
                    SELECT id, name, user_id, project_id, working_dir, display_order,
                           is_alive, created_at, last_accessed_at
                    FROM terminal_sessions
                    ORDER BY display_order, created_at
                    """
                )
            else:
                cur.execute(
                    """
                    SELECT id, name, user_id, project_id, working_dir, display_order,
                           is_alive, created_at, last_accessed_at
                    FROM terminal_sessions
                    WHERE is_alive = true
                    ORDER BY display_order, created_at
                    """
                )
        rows = cur.fetchall()

    return [_row_to_dict(row) for row in rows]


def get_session(session_id: str | UUID) -> dict[str, Any] | None:
    """Get a session by ID.

    Args:
        session_id: Session UUID (string or UUID)

    Returns:
        Session dict or None if not found
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, name, user_id, project_id, working_dir, display_order,
                   is_alive, created_at, last_accessed_at
            FROM terminal_sessions
            WHERE id = %s
            """,
            (str(session_id),),
        )
        row = cur.fetchone()

    if not row:
        return None
    return _row_to_dict(row)


def create_session(
    name: str,
    project_id: str | None = None,
    working_dir: str | None = None,
    user_id: str | None = None,
) -> str:
    """Create a new terminal session.

    The session ID is generated server-side to prevent client collisions.

    Args:
        name: Display name for the session
        project_id: Optional project ID for context
        working_dir: Initial working directory (default: user home)
        user_id: Optional user ID (for future auth support)

    Returns:
        Server-generated session UUID as string
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO terminal_sessions (name, user_id, project_id, working_dir)
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (name, user_id, project_id, working_dir),
        )
        row = cur.fetchone()
        conn.commit()

    if not row:
        raise ValueError("Failed to create terminal session")

    return str(row[0])


def update_session(session_id: str | UUID, **fields: Any) -> dict[str, Any] | None:
    """Update session metadata.

    Allowed fields: name, display_order, is_alive, working_dir

    Args:
        session_id: Session UUID
        **fields: Fields to update

    Returns:
        Updated session dict or None if not found
    """
    allowed_fields = {"name", "display_order", "is_alive", "working_dir"}
    update_fields = {k: v for k, v in fields.items() if k in allowed_fields}

    if not update_fields:
        return get_session(session_id)

    set_clauses = [
        psycopg.sql.SQL("{} = %s").format(psycopg.sql.Identifier(field)) for field in update_fields
    ]
    values = list(update_fields.values())
    values.append(str(session_id))

    query = psycopg.sql.SQL("""
        UPDATE terminal_sessions
        SET {}
        WHERE id = %s
        RETURNING id, name, user_id, project_id, working_dir, display_order,
                  is_alive, created_at, last_accessed_at
    """).format(psycopg.sql.SQL(", ").join(set_clauses))

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(query, values)
        row = cur.fetchone()
        conn.commit()

    if not row:
        return None
    return _row_to_dict(row)


def delete_session(session_id: str | UUID) -> bool:
    """Delete a session (hard delete).

    Use this when user explicitly closes the terminal.

    Args:
        session_id: Session UUID

    Returns:
        True if deleted, False if not found
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM terminal_sessions WHERE id = %s RETURNING id",
            (str(session_id),),
        )
        result = cur.fetchone()
        conn.commit()

    return result is not None


def mark_dead(session_id: str | UUID) -> dict[str, Any] | None:
    """Mark a session as dead (tmux session no longer exists).

    The session record is preserved for potential recovery.

    Args:
        session_id: Session UUID

    Returns:
        Updated session dict or None if not found
    """
    return update_session(session_id, is_alive=False)


def touch_session(session_id: str | UUID) -> dict[str, Any] | None:
    """Update last_accessed_at timestamp.

    Call this on WebSocket connect to track session activity.

    Args:
        session_id: Session UUID

    Returns:
        Updated session dict or None if not found
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE terminal_sessions
            SET last_accessed_at = NOW()
            WHERE id = %s
            RETURNING id, name, user_id, project_id, working_dir, display_order,
                      is_alive, created_at, last_accessed_at
            """,
            (str(session_id),),
        )
        row = cur.fetchone()
        conn.commit()

    if not row:
        return None
    return _row_to_dict(row)


def list_orphaned(older_than_days: int = 30) -> list[dict[str, Any]]:
    """List sessions not accessed in N days.

    Used by cleanup job to find abandoned sessions.

    Args:
        older_than_days: Days since last access (default 30)

    Returns:
        List of orphaned session dicts
    """
    cutoff = datetime.utcnow() - timedelta(days=older_than_days)

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, name, user_id, project_id, working_dir, display_order,
                   is_alive, created_at, last_accessed_at
            FROM terminal_sessions
            WHERE last_accessed_at < %s
            ORDER BY last_accessed_at
            """,
            (cutoff,),
        )
        rows = cur.fetchall()

    return [_row_to_dict(row) for row in rows]


def _row_to_dict(row: tuple) -> dict[str, Any]:
    """Convert a database row to a session dict."""
    return {
        "id": str(row[0]),
        "name": row[1],
        "user_id": row[2],
        "project_id": row[3],
        "working_dir": row[4],
        "display_order": row[5],
        "is_alive": row[6],
        "created_at": row[7],
        "last_accessed_at": row[8],
    }
