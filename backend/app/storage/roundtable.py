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
    tools_enabled: bool | None = None,
    write_enabled: bool | None = None,
    yolo_mode: bool | None = None,
    tool_stats: dict[str, Any] | None = None,
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

    Returns:
        Saved session dict
    """
    features = generated_features or []
    default_stats = {"total_calls": 0, "files_read": 0, "searches": 0, "writes": 0}

    with get_connection() as conn, conn.cursor() as cur:
        # Build dynamic update based on what's provided
        if tools_enabled is not None or write_enabled is not None or yolo_mode is not None or tool_stats is not None:
            # Full update including tools fields
            cur.execute(
                """
                INSERT INTO roundtable_sessions
                    (id, project_id, mode, tools_enabled, write_enabled, yolo_mode, tool_stats, messages, generated_features, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, NOW(), NOW())
                ON CONFLICT (id) DO UPDATE SET
                    messages = EXCLUDED.messages,
                    generated_features = COALESCE(NULLIF(EXCLUDED.generated_features, '[]'::jsonb), roundtable_sessions.generated_features),
                    tools_enabled = COALESCE(EXCLUDED.tools_enabled, roundtable_sessions.tools_enabled),
                    write_enabled = COALESCE(EXCLUDED.write_enabled, roundtable_sessions.write_enabled),
                    yolo_mode = COALESCE(EXCLUDED.yolo_mode, roundtable_sessions.yolo_mode),
                    tool_stats = COALESCE(EXCLUDED.tool_stats, roundtable_sessions.tool_stats),
                    updated_at = NOW()
                RETURNING id, project_id, mode, tools_enabled, write_enabled, yolo_mode, tool_stats, messages, generated_features, created_at, updated_at
                """,
                (
                    session_id,
                    project_id,
                    mode,
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
                    (id, project_id, mode, messages, generated_features, created_at, updated_at)
                VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, NOW(), NOW())
                ON CONFLICT (id) DO UPDATE SET
                    messages = EXCLUDED.messages,
                    generated_features = COALESCE(NULLIF(EXCLUDED.generated_features, '[]'::jsonb), roundtable_sessions.generated_features),
                    updated_at = NOW()
                RETURNING id, project_id, mode, tools_enabled, write_enabled, yolo_mode, tool_stats, messages, generated_features, created_at, updated_at
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
        "tools_enabled": row[3] if row[3] is not None else True,
        "write_enabled": row[4] if row[4] is not None else False,
        "yolo_mode": row[5] if row[5] is not None else False,
        "tool_stats": row[6] or default_stats,
        "messages": row[7] or [],
        "generated_features": row[8] or [],
        "created_at": row[9],
        "updated_at": row[10],
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
                   claude_sdk_session_id, gemini_sdk_session_id
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
    default_stats = {"total_calls": 0, "files_read": 0, "searches": 0, "writes": 0}

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, project_id, mode, tools_enabled, write_enabled, yolo_mode, tool_stats,
                   agent_override, model_override,
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
            "tools_enabled": row[3] if row[3] is not None else True,
            "write_enabled": row[4] if row[4] is not None else False,
            "yolo_mode": row[5] if row[5] is not None else False,
            "tool_stats": row[6] or default_stats,
            "agent_override": row[7],
            "model_override": row[8],
            "message_count": row[9],
            "feature_count": row[10],
            "created_at": row[11],
            "updated_at": row[12],
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


def update_tools_settings(
    session_id: str,
    tools_enabled: bool | None = None,
    write_enabled: bool | None = None,
    yolo_mode: bool | None = None,
) -> dict[str, Any] | None:
    """Update tools settings for a session.

    Args:
        session_id: Session ID
        tools_enabled: Whether read tools should be enabled (optional)
        write_enabled: Whether write tools should be enabled (optional)
        yolo_mode: Whether YOLO mode should be enabled (optional)

    Returns:
        Updated session dict or None if not found
    """
    default_stats = {"total_calls": 0, "files_read": 0, "searches": 0, "writes": 0}

    # Build SET clause dynamically based on provided fields
    set_parts = ["updated_at = NOW()"]
    params = []

    if tools_enabled is not None:
        set_parts.append("tools_enabled = %s")
        params.append(tools_enabled)
    if write_enabled is not None:
        set_parts.append("write_enabled = %s")
        params.append(write_enabled)
    if yolo_mode is not None:
        set_parts.append("yolo_mode = %s")
        params.append(yolo_mode)

    params.append(session_id)

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE roundtable_sessions
            SET {', '.join(set_parts)}
            WHERE id = %s
            RETURNING id, project_id, mode, tools_enabled, write_enabled, yolo_mode, tool_stats, created_at, updated_at
            """,
            params,
        )
        row = cur.fetchone()
        conn.commit()

    if not row:
        return None

    return {
        "id": row[0],
        "project_id": row[1],
        "mode": row[2],
        "tools_enabled": row[3],
        "write_enabled": row[4] if row[4] is not None else False,
        "yolo_mode": row[5] if row[5] is not None else False,
        "tool_stats": row[6] or default_stats,
        "created_at": row[7],
        "updated_at": row[8],
    }


# Backwards compatibility alias
def update_tools_enabled(session_id: str, tools_enabled: bool) -> dict[str, Any] | None:
    """Backwards compatible wrapper for update_tools_settings."""
    return update_tools_settings(session_id, tools_enabled=tools_enabled)


def update_tool_stats(
    session_id: str,
    tool_stats: dict[str, Any],
) -> bool:
    """Update tool usage statistics for a session.

    Args:
        session_id: Session ID
        tool_stats: Tool usage statistics dict

    Returns:
        True if updated, False if session not found
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE roundtable_sessions
            SET tool_stats = %s::jsonb,
                updated_at = NOW()
            WHERE id = %s
            RETURNING id
            """,
            (json.dumps(tool_stats), session_id),
        )
        result = cur.fetchone()
        conn.commit()

    return result is not None


def increment_tool_stats(
    session_id: str,
    tool_name: str,
) -> bool:
    """Increment tool usage statistics for a session.

    Args:
        session_id: Session ID
        tool_name: Name of the tool that was called

    Returns:
        True if updated, False if session not found
    """
    # Map tool names to stat fields
    stat_field = "total_calls"
    if tool_name == "read_file":
        additional_field = "files_read"
    elif tool_name in ("search_code", "list_files"):
        additional_field = "searches"
    else:
        additional_field = None

    with get_connection() as conn, conn.cursor() as cur:
        if additional_field:
            cur.execute(
                """
                UPDATE roundtable_sessions
                SET tool_stats = jsonb_set(
                    jsonb_set(
                        COALESCE(tool_stats, '{"total_calls": 0, "files_read": 0, "searches": 0}'::jsonb),
                        '{total_calls}',
                        (COALESCE((tool_stats->>'total_calls')::int, 0) + 1)::text::jsonb
                    ),
                    %s::text[],
                    (COALESCE((tool_stats->>%s)::int, 0) + 1)::text::jsonb
                ),
                    updated_at = NOW()
                WHERE id = %s
                RETURNING id
                """,
                ([additional_field], additional_field, session_id),
            )
        else:
            cur.execute(
                """
                UPDATE roundtable_sessions
                SET tool_stats = jsonb_set(
                    COALESCE(tool_stats, '{"total_calls": 0, "files_read": 0, "searches": 0}'::jsonb),
                    '{total_calls}',
                    (COALESCE((tool_stats->>'total_calls')::int, 0) + 1)::text::jsonb
                ),
                    updated_at = NOW()
                WHERE id = %s
                RETURNING id
                """,
                (session_id,),
            )
        result = cur.fetchone()
        conn.commit()

    return result is not None


def update_agent_config(
    session_id: str,
    agent_override: str | None = None,
    model_override: str | None = None,
) -> bool:
    """Update agent configuration override for a session.

    Args:
        session_id: Session ID
        agent_override: Override agent type (claude/gemini) or None to clear
        model_override: Override model ID or None to clear

    Returns:
        True if session was updated, False if not found
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE roundtable_sessions
            SET agent_override = %s,
                model_override = %s,
                updated_at = NOW()
            WHERE id = %s
            RETURNING id
            """,
            (agent_override, model_override, session_id),
        )
        result = cur.fetchone()
        conn.commit()

    return result is not None


def update_sdk_session_ids(
    session_id: str,
    claude_sdk_session_id: str | None = None,
    gemini_sdk_session_id: str | None = None,
) -> bool:
    """Update SDK session IDs for session resume.

    Args:
        session_id: Roundtable session ID
        claude_sdk_session_id: Claude Agent SDK session ID for resume
        gemini_sdk_session_id: Gemini session ID for resume

    Returns:
        True if session was updated, False if not found
    """
    # Build SET clause dynamically - only update provided fields
    set_parts = ["updated_at = NOW()"]
    params = []

    if claude_sdk_session_id is not None:
        set_parts.append("claude_sdk_session_id = %s")
        params.append(claude_sdk_session_id)
    if gemini_sdk_session_id is not None:
        set_parts.append("gemini_sdk_session_id = %s")
        params.append(gemini_sdk_session_id)

    params.append(session_id)

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE roundtable_sessions
            SET {', '.join(set_parts)}
            WHERE id = %s
            RETURNING id
            """,
            params,
        )
        result = cur.fetchone()
        conn.commit()

    return result is not None


def update_session_metadata(
    session_id: str,
    title: str | None = None,
    description: str | None = None,
    status: str | None = None,
    agent_mode: str | None = None,
) -> dict[str, Any] | None:
    """Update session metadata fields.

    Args:
        session_id: Session ID
        title: Session title (optional)
        description: Session description (optional)
        status: Session status - active, archived (optional)
        agent_mode: Agent mode - claude, gemini, both (optional)

    Returns:
        Updated session dict or None if not found
    """
    # Build SET clause dynamically based on provided fields
    set_parts = ["updated_at = NOW()"]
    params = []

    if title is not None:
        set_parts.append("title = %s")
        params.append(title)
    if description is not None:
        set_parts.append("description = %s")
        params.append(description)
    if status is not None:
        set_parts.append("status = %s")
        params.append(status)
    if agent_mode is not None:
        set_parts.append("agent_mode = %s")
        params.append(agent_mode)

    params.append(session_id)

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE roundtable_sessions
            SET {', '.join(set_parts)}
            WHERE id = %s
            RETURNING id, project_id, title, description, status, agent_mode,
                      mode, tools_enabled, claude_sdk_session_id, gemini_sdk_session_id,
                      created_at, updated_at
            """,
            params,
        )
        row = cur.fetchone()
        conn.commit()

    if not row:
        return None

    return {
        "id": row[0],
        "project_id": row[1],
        "title": row[2],
        "description": row[3],
        "status": row[4],
        "agent_mode": row[5],
        "mode": row[6],
        "tools_enabled": row[7],
        "claude_sdk_session_id": row[8],
        "gemini_sdk_session_id": row[9],
        "created_at": row[10],
        "updated_at": row[11],
    }


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
