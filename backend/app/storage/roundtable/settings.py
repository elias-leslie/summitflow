"""Session settings and configuration operations for roundtable storage."""

from __future__ import annotations

import json
from typing import Any

from psycopg import sql

from ..connection import get_connection


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
    set_parts: list[sql.Composable] = [sql.SQL("updated_at = NOW()")]
    params: list[bool | str] = []

    if tools_enabled is not None:
        set_parts.append(sql.SQL("tools_enabled = %s"))
        params.append(tools_enabled)
    if write_enabled is not None:
        set_parts.append(sql.SQL("write_enabled = %s"))
        params.append(write_enabled)
    if yolo_mode is not None:
        set_parts.append(sql.SQL("yolo_mode = %s"))
        params.append(yolo_mode)

    params.append(session_id)

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            sql.SQL("""
            UPDATE roundtable_sessions
            SET {set_parts}
            WHERE id = %s
            RETURNING id, project_id, mode, tools_enabled, write_enabled, yolo_mode, tool_stats, created_at, updated_at
            """).format(set_parts=sql.SQL(", ").join(set_parts)),
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
    set_parts: list[sql.Composable] = [sql.SQL("updated_at = NOW()")]
    params: list[str] = []

    if claude_sdk_session_id is not None:
        set_parts.append(sql.SQL("claude_sdk_session_id = %s"))
        params.append(claude_sdk_session_id)
    if gemini_sdk_session_id is not None:
        set_parts.append(sql.SQL("gemini_sdk_session_id = %s"))
        params.append(gemini_sdk_session_id)

    params.append(session_id)

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            sql.SQL("""
            UPDATE roundtable_sessions
            SET {set_parts}
            WHERE id = %s
            RETURNING id
            """).format(set_parts=sql.SQL(", ").join(set_parts)),
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
    set_parts: list[sql.Composable] = [sql.SQL("updated_at = NOW()")]
    params: list[str] = []

    if title is not None:
        set_parts.append(sql.SQL("title = %s"))
        params.append(title)
    if description is not None:
        set_parts.append(sql.SQL("description = %s"))
        params.append(description)
    if status is not None:
        set_parts.append(sql.SQL("status = %s"))
        params.append(status)
    if agent_mode is not None:
        set_parts.append(sql.SQL("agent_mode = %s"))
        params.append(agent_mode)

    params.append(session_id)

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            sql.SQL("""
            UPDATE roundtable_sessions
            SET {set_parts}
            WHERE id = %s
            RETURNING id, project_id, title, description, status, agent_mode,
                      mode, tools_enabled, claude_sdk_session_id, gemini_sdk_session_id,
                      created_at, updated_at
            """).format(set_parts=sql.SQL(", ").join(set_parts)),
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
