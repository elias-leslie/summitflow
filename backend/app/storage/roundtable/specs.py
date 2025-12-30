"""TDD spec storage operations for roundtable."""

from __future__ import annotations

import json
from typing import Any

from ..connection import get_connection


def update_generated_spec(
    session_id: str,
    spec: dict[str, Any] | None,
) -> bool:
    """Update the generated spec for a session.

    Args:
        session_id: Session ID
        spec: Spec dict with components, capabilities, tests structure or None to clear

    Returns:
        True if updated, False if session not found
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE roundtable_sessions
            SET generated_spec = %s::jsonb,
                updated_at = NOW()
            WHERE id = %s
            RETURNING id
            """,
            (json.dumps(spec) if spec else None, session_id),
        )
        result = cur.fetchone()
        conn.commit()

    return result is not None


def get_generated_spec(session_id: str) -> dict[str, Any] | None:
    """Get the generated spec for a session.

    Args:
        session_id: Session ID

    Returns:
        Spec dict or None if not found or no spec exists
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT generated_spec FROM roundtable_sessions WHERE id = %s",
            (session_id,),
        )
        row = cur.fetchone()

    if not row or not row[0]:
        return None

    return dict(row[0])
