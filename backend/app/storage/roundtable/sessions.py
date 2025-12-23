"""Session CRUD operations for roundtable storage."""

from __future__ import annotations

import json
from typing import Any, Literal

from ..connection import get_connection


def save_session(
    session_id: str,
    project_id: str,
    mode: Literal["spec_driven", "quick"],
    messages: list[dict[str, Any]],
    generated_features: list[dict[str, Any]] | None = None,
    tools_enabled: bool | None = None,
    write_enabled: bool | None = None,
    yolo_mode: bool | None = None,
    tool_stats: dict[str, Any] | None = None,
    title: str | None = None,
    agent_mode: str | None = None,
) -> dict[str, Any]:
    """Save or update a roundtable session.

    Args:
        session_id: Unique session ID
        project_id: Project ID
        mode: Session mode (spec_driven or quick)
        messages: List of message dicts
        generated_features: List of generated feature dicts (optional)
        tools_enabled: Whether read tools are enabled (optional, preserves existing if None)
        write_enabled: Whether write tools are enabled (optional, preserves existing if None)
        yolo_mode: Whether YOLO mode is enabled (optional, preserves existing if None)
        tool_stats: Tool usage statistics (optional, preserves existing if None)
        title: Session title (optional)
        agent_mode: Agent mode - claude, gemini, both (optional)

    Returns:
        Saved session dict
    """
    features = generated_features or []
    default_stats = {"total_calls": 0, "files_read": 0, "searches": 0, "writes": 0}

    with get_connection() as conn, conn.cursor() as cur:
        # Build dynamic update based on what's provided
        if (
            tools_enabled is not None
            or write_enabled is not None
            or yolo_mode is not None
            or tool_stats is not None
        ):
            # Full update including tools fields
            cur.execute(
                """
                INSERT INTO roundtable_sessions
                    (id, project_id, mode, title, agent_mode, status, tools_enabled, write_enabled, yolo_mode, tool_stats, messages, generated_features, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, 'active', %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, NOW(), NOW())
                ON CONFLICT (id) DO UPDATE SET
                    messages = EXCLUDED.messages,
                    generated_features = COALESCE(NULLIF(EXCLUDED.generated_features, '[]'::jsonb), roundtable_sessions.generated_features),
                    tools_enabled = COALESCE(EXCLUDED.tools_enabled, roundtable_sessions.tools_enabled),
                    write_enabled = COALESCE(EXCLUDED.write_enabled, roundtable_sessions.write_enabled),
                    yolo_mode = COALESCE(EXCLUDED.yolo_mode, roundtable_sessions.yolo_mode),
                    tool_stats = COALESCE(EXCLUDED.tool_stats, roundtable_sessions.tool_stats),
                    updated_at = NOW()
                RETURNING id, project_id, mode, title, status, agent_mode, tools_enabled, write_enabled, yolo_mode, tool_stats, messages, generated_features, created_at, updated_at
                """,
                (
                    session_id,
                    project_id,
                    mode,
                    title,
                    agent_mode or "both",
                    tools_enabled if tools_enabled is not None else True,
                    write_enabled if write_enabled is not None else False,
                    yolo_mode if yolo_mode is not None else False,
                    json.dumps(tool_stats if tool_stats is not None else default_stats),
                    json.dumps(messages),
                    json.dumps(features),
                ),
            )
        else:
            # Original query for backwards compatibility
            cur.execute(
                """
                INSERT INTO roundtable_sessions
                    (id, project_id, mode, title, agent_mode, status, messages, generated_features, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, 'active', %s::jsonb, %s::jsonb, NOW(), NOW())
                ON CONFLICT (id) DO UPDATE SET
                    messages = EXCLUDED.messages,
                    generated_features = COALESCE(NULLIF(EXCLUDED.generated_features, '[]'::jsonb), roundtable_sessions.generated_features),
                    updated_at = NOW()
                RETURNING id, project_id, mode, title, status, agent_mode, tools_enabled, write_enabled, yolo_mode, tool_stats, messages, generated_features, created_at, updated_at
                """,
                (
                    session_id,
                    project_id,
                    mode,
                    title,
                    agent_mode or "both",
                    json.dumps(messages),
                    json.dumps(features),
                ),
            )
        row = cur.fetchone()
        conn.commit()

    if not row:
        raise RuntimeError(f"Failed to save session {session_id}")

    return {
        "id": row[0],
        "project_id": row[1],
        "mode": row[2],
        "title": row[3],
        "status": row[4] or "active",
        "agent_mode": row[5] or "both",
        "tools_enabled": row[6] if row[6] is not None else True,
        "write_enabled": row[7] if row[7] is not None else False,
        "yolo_mode": row[8] if row[8] is not None else False,
        "tool_stats": row[9] or default_stats,
        "messages": row[10] or [],
        "generated_features": row[11] or [],
        "created_at": row[12],
        "updated_at": row[13],
    }


def load_session(session_id: str) -> dict[str, Any] | None:
    """Load a roundtable session by ID.

    Args:
        session_id: Session ID

    Returns:
        Session dict or None if not found
    """
    default_stats = {"total_calls": 0, "files_read": 0, "searches": 0, "writes": 0}

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, project_id, mode, tools_enabled, write_enabled, yolo_mode, tool_stats,
                   agent_override, model_override, messages, generated_features, created_at, updated_at,
                   claude_sdk_session_id, gemini_sdk_session_id, generated_spec
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
        "tools_enabled": row[3] if row[3] is not None else True,
        "write_enabled": row[4] if row[4] is not None else False,
        "yolo_mode": row[5] if row[5] is not None else False,
        "tool_stats": row[6] or default_stats,
        "agent_override": row[7],
        "model_override": row[8],
        "messages": row[9] or [],
        "generated_features": row[10] or [],
        "created_at": row[11],
        "updated_at": row[12],
        "claude_sdk_session_id": row[13],
        "gemini_sdk_session_id": row[14],
        "generated_spec": row[15],
    }


def list_sessions(
    project_id: str,
    limit: int = 20,
    offset: int = 0,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """List roundtable sessions for a project.

    Args:
        project_id: Project ID
        limit: Maximum number of sessions to return
        offset: Number of sessions to skip
        status: Filter by status ("active", "archived") or None for all

    Returns:
        List of session dicts (without full messages for performance)
    """
    default_stats = {"total_calls": 0, "files_read": 0, "searches": 0, "writes": 0}

    with get_connection() as conn, conn.cursor() as cur:
        query = """
            SELECT id, project_id, title, status, mode, agent_mode,
                   tools_enabled, write_enabled, yolo_mode, tool_stats,
                   agent_override, model_override,
                   jsonb_array_length(messages) as message_count,
                   jsonb_array_length(generated_features) as feature_count,
                   created_at, updated_at
            FROM roundtable_sessions
            WHERE project_id = %s
        """
        params: list[str | int] = [project_id]

        if status:
            query += " AND status = %s"
            params.append(status)

        query += " ORDER BY updated_at DESC LIMIT %s OFFSET %s"
        params.extend([limit, offset])

        cur.execute(query, params)
        rows = cur.fetchall()

    return [
        {
            "id": row[0],
            "project_id": row[1],
            "title": row[2],
            "status": row[3] or "active",
            "mode": row[4],
            "agent_mode": row[5] or "both",
            "tools_enabled": row[6] if row[6] is not None else True,
            "write_enabled": row[7] if row[7] is not None else False,
            "yolo_mode": row[8] if row[8] is not None else False,
            "tool_stats": row[9] or default_stats,
            "agent_override": row[10],
            "model_override": row[11],
            "message_count": row[12],
            "feature_count": row[13],
            "created_at": row[14],
            "updated_at": row[15],
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


def get_session_count(project_id: str) -> int:
    """Get the number of roundtable sessions for a project.

    Args:
        project_id: Project ID

    Returns:
        Number of sessions
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM roundtable_sessions WHERE project_id = %s",
            (project_id,),
        )
        row = cur.fetchone()

    return row[0] if row else 0


def delete_oldest_session(project_id: str) -> str | None:
    """Delete the oldest session for a project.

    Used to enforce session limits (e.g., max 25 per project).

    Args:
        project_id: Project ID

    Returns:
        Deleted session ID or None if no sessions exist
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM roundtable_sessions
            WHERE id = (
                SELECT id FROM roundtable_sessions
                WHERE project_id = %s
                ORDER BY updated_at ASC
                LIMIT 1
            )
            RETURNING id
            """,
            (project_id,),
        )
        row = cur.fetchone()
        conn.commit()

    return row[0] if row else None
