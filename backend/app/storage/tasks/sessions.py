"""Tasks storage - Agent Hub session management.

This module provides functions to link tasks with Agent Hub sessions.
"""

from __future__ import annotations

from typing import Any

from ..connection import get_connection
from .columns import TASK_COLUMNS
from .mapping import row_to_dict


def add_agent_hub_session(task_id: str, session_id: str) -> dict[str, Any] | None:
    """Add an Agent Hub session ID to a task.

    Appends the session_id to the agent_hub_session_ids array if not already present.
    This links the task to Agent Hub sessions for full observability.

    Args:
        task_id: Task ID
        session_id: Agent Hub session ID to add

    Returns:
        Updated task dict or None if task not found.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE tasks
            SET agent_hub_session_ids = array_append(
                COALESCE(agent_hub_session_ids, ARRAY[]::TEXT[]),
                %s
            )
            WHERE id = %s
            AND NOT (%s = ANY(COALESCE(agent_hub_session_ids, ARRAY[]::TEXT[])))
            RETURNING {TASK_COLUMNS}
            """,
            (session_id, task_id, session_id),
        )
        row = cur.fetchone()
        conn.commit()

    # If no row returned, either task not found or session_id already exists
    # Try to fetch the task to distinguish
    if not row:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT {TASK_COLUMNS} FROM tasks WHERE id = %s",
                (task_id,),
            )
            row = cur.fetchone()

    if not row:
        return None
    return row_to_dict(row)


def get_agent_hub_sessions(task_id: str) -> list[str]:
    """Get Agent Hub session IDs for a task.

    Args:
        task_id: Task ID

    Returns:
        List of Agent Hub session IDs (empty if task not found or no sessions).
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT agent_hub_session_ids FROM tasks WHERE id = %s",
            (task_id,),
        )
        row = cur.fetchone()

    if not row or not row[0]:
        return []
    return list(row[0])
