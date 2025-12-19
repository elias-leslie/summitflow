"""Roundtable session storage - Persistence for multi-agent chat sessions.

This module provides data access for roundtable sessions including
messages and generated features.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from .connection import get_connection


def save_session(
    session_id: str,
    project_id: str,
    mode: Literal["spec_driven", "quick"],
    messages: list[dict[str, Any]],
    generated_features: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Save or update a roundtable session.

    Args:
        session_id: Unique session ID
        project_id: Project ID
        mode: Session mode (spec_driven or quick)
        messages: List of message dicts
        generated_features: List of generated feature dicts (optional)

    Returns:
        Saved session dict
    """
    features = generated_features or []

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO roundtable_sessions
                (id, project_id, mode, messages, generated_features, created_at, updated_at)
            VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, NOW(), NOW())
            ON CONFLICT (id) DO UPDATE SET
                messages = EXCLUDED.messages,
                generated_features = EXCLUDED.generated_features,
                updated_at = NOW()
            RETURNING id, project_id, mode, messages, generated_features, created_at, updated_at
            """,
            (session_id, project_id, mode, json.dumps(messages), json.dumps(features)),
        )
        row = cur.fetchone()
        conn.commit()

    if not row:
        raise RuntimeError(f"Failed to save session {session_id}")

    return {
        "id": row[0],
        "project_id": row[1],
        "mode": row[2],
        "messages": row[3] or [],
        "generated_features": row[4] or [],
        "created_at": row[5],
        "updated_at": row[6],
    }


def load_session(session_id: str) -> dict[str, Any] | None:
    """Load a roundtable session by ID.

    Args:
        session_id: Session ID

    Returns:
        Session dict or None if not found
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, project_id, mode, messages, generated_features, created_at, updated_at
            FROM roundtable_sessions
            WHERE id = %s
            """,
            (session_id,),
        )
        row = cur.fetchone()

    if not row:
        return None

    return {
        "id": row[0],
        "project_id": row[1],
        "mode": row[2],
        "messages": row[3] or [],
        "generated_features": row[4] or [],
        "created_at": row[5],
        "updated_at": row[6],
    }


def list_sessions(
    project_id: str,
    limit: int = 20,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """List roundtable sessions for a project.

    Args:
        project_id: Project ID
        limit: Maximum number of sessions to return
        offset: Number of sessions to skip

    Returns:
        List of session dicts (without full messages for performance)
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, project_id, mode,
                   jsonb_array_length(messages) as message_count,
                   jsonb_array_length(generated_features) as feature_count,
                   created_at, updated_at
            FROM roundtable_sessions
            WHERE project_id = %s
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
            """,
            (project_id, limit, offset),
        )
        rows = cur.fetchall()

    return [
        {
            "id": row[0],
            "project_id": row[1],
            "mode": row[2],
            "message_count": row[3],
            "feature_count": row[4],
            "created_at": row[5],
            "updated_at": row[6],
        }
        for row in rows
    ]


def delete_session(session_id: str) -> bool:
    """Delete a roundtable session.

    Args:
        session_id: Session ID

    Returns:
        True if deleted, False if not found
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM roundtable_sessions WHERE id = %s RETURNING id",
            (session_id,),
        )
        result = cur.fetchone()
        conn.commit()

    return result is not None


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
