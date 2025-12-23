"""Message and feature operations for roundtable storage."""

from __future__ import annotations

import json
from typing import Any

from ..connection import get_connection


def add_message_to_session(
    session_id: str,
    message: dict[str, Any],
) -> bool:
    """Append a message to an existing session.

    Args:
        session_id: Session ID
        message: Message dict to append

    Returns:
        True if updated, False if session not found
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE roundtable_sessions
            SET messages = messages || %s::jsonb,
                updated_at = NOW()
            WHERE id = %s
            RETURNING id
            """,
            (json.dumps([message]), session_id),
        )
        result = cur.fetchone()
        conn.commit()

    return result is not None


def update_generated_features(
    session_id: str,
    features: list[dict[str, Any]],
) -> bool:
    """Update the generated features for a session.

    Args:
        session_id: Session ID
        features: List of generated feature dicts

    Returns:
        True if updated, False if session not found
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE roundtable_sessions
            SET generated_features = %s::jsonb,
                updated_at = NOW()
            WHERE id = %s
            RETURNING id
            """,
            (json.dumps(features), session_id),
        )
        result = cur.fetchone()
        conn.commit()

    return result is not None
