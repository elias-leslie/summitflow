"""Memory checkpoints storage - Agent checkpoint CRUD operations.

This module handles the agent_checkpoints table operations.
"""

from __future__ import annotations

import logging
from typing import Any, TypedDict

from psycopg.rows import TupleRow

from .agent_configs import is_memory_feature_enabled
from .connection import get_connection
from .memory_utils import (
    json_or_default,
    normalize_timestamp,
)

logger = logging.getLogger(__name__)

DEFAULT_CHECKPOINT_RETENTION_DAYS = 30

# Column list for DRY queries
CHECKPOINT_COLUMNS = """
    id, project_id, session_id, agent_type, current_action,
    question, options, recommendation, completed_steps,
    remaining_steps, files_modified, decisions_made,
    conversation_summary, context_snapshot, tokens_used, created_at
""".strip()


class CheckpointDict(TypedDict, total=False):
    """Type definition for checkpoint data."""

    id: str
    project_id: str
    session_id: str
    agent_type: str
    current_action: str | None
    question: str | None
    options: list[str] | None
    recommendation: str | None
    completed_steps: list[str] | None
    remaining_steps: list[str] | None
    files_modified: list[str] | None
    decisions_made: list[str] | None
    conversation_summary: str | None
    context_snapshot: dict[str, Any] | None
    tokens_used: int | None
    created_at: str | None


def _checkpoint_row_to_dict(row: TupleRow | tuple[Any, ...] | None) -> dict[str, Any]:
    """Convert checkpoint row to dict."""
    if row is None:
        raise ValueError("Row cannot be None")
    return {
        "id": str(row[0]),
        "project_id": row[1],
        "session_id": row[2],
        "agent_type": row[3],
        "current_action": row[4],
        "question": row[5],
        "options": row[6],
        "recommendation": row[7],
        "completed_steps": row[8],
        "remaining_steps": row[9],
        "files_modified": row[10],
        "decisions_made": row[11],
        "conversation_summary": row[12],
        "context_snapshot": row[13],
        "tokens_used": row[14],
        "created_at": normalize_timestamp(row[15]),
    }


def create_checkpoint(
    project_id: str,
    session_id: str,
    agent_type: str,
    current_action: str | None = None,
    question: str | None = None,
    options: list[dict[str, Any]] | None = None,
    recommendation: str | None = None,
    completed_steps: list[str] | None = None,
    remaining_steps: list[str] | None = None,
    files_modified: list[str] | None = None,
    decisions_made: list[dict[str, Any]] | None = None,
    conversation_summary: str | None = None,
    context_snapshot: dict[str, Any] | None = None,
    tokens_used: int | None = None,
    skip_memory_check: bool = False,
) -> dict[str, Any] | None:
    """Create an agent checkpoint.

    Args:
        skip_memory_check: If True, bypass the memory enabled check.

    Returns:
        The created checkpoint, or None if memory is disabled.
    """
    if not skip_memory_check and not is_memory_feature_enabled(project_id, "checkpoints"):
        logger.debug(f"Memory checkpoints disabled for {project_id}, skipping checkpoint")
        return None

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO agent_checkpoints
                (project_id, session_id, agent_type, current_action, question,
                 options, recommendation, completed_steps, remaining_steps,
                 files_modified, decisions_made, conversation_summary,
                 context_snapshot, tokens_used)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, project_id, session_id, agent_type, current_action,
                      question, options, recommendation, completed_steps,
                      remaining_steps, files_modified, decisions_made,
                      conversation_summary, context_snapshot, tokens_used, created_at
            """,
            (
                project_id,
                session_id,
                agent_type,
                current_action,
                question,
                json_or_default(options),
                recommendation,
                json_or_default(completed_steps),
                json_or_default(remaining_steps),
                json_or_default(files_modified),
                json_or_default(decisions_made),
                conversation_summary,
                json_or_default(context_snapshot),
                tokens_used,
            ),
        )
        row = cur.fetchone()
        conn.commit()

    return _checkpoint_row_to_dict(row)


def get_latest_checkpoint(session_id: str) -> dict[str, Any] | None:
    """Get the most recent checkpoint for a session."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {CHECKPOINT_COLUMNS}
            FROM agent_checkpoints
            WHERE session_id = %s
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (session_id,),
        )
        row = cur.fetchone()

    if not row:
        return None
    return _checkpoint_row_to_dict(row)


def list_checkpoints(
    project_id: str,
    limit: int = 20,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """List checkpoints for a project."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {CHECKPOINT_COLUMNS}
            FROM agent_checkpoints
            WHERE project_id = %s
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
            """,
            (project_id, limit, offset),
        )
        rows = cur.fetchall()

    return [_checkpoint_row_to_dict(row) for row in rows]


def delete_checkpoint(checkpoint_id: str) -> bool:
    """Delete a checkpoint.

    Returns:
        True if deleted, False if not found.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM agent_checkpoints WHERE id = %s",
            (checkpoint_id,),
        )
        deleted = cur.rowcount > 0
        conn.commit()

    return deleted


def cleanup_old_checkpoints(max_age_days: int = DEFAULT_CHECKPOINT_RETENTION_DAYS) -> int:
    """Delete old checkpoints beyond the retention period.

    Args:
        max_age_days: Delete checkpoints older than this many days.

    Returns:
        Number of checkpoints deleted.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM agent_checkpoints
            WHERE created_at < NOW() - INTERVAL '%s days'
            """,
            (max_age_days,),
        )
        deleted = cur.rowcount
        conn.commit()

    logger.info(
        f"cleanup_old_checkpoints: deleted {deleted} checkpoints older than {max_age_days} days"
    )
    return deleted
