"""Build state management for agent sessions."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ..connection import get_connection


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
