"""Memory queue storage - Observation queue management for async processing.

This module handles the observation_queue table operations.
"""

from __future__ import annotations

import logging
from typing import Any

from psycopg.rows import TupleRow

from .agent_configs import is_memory_feature_enabled
from .connection import get_connection
from .memory_utils import json_or_default as _json_or_default

logger = logging.getLogger(__name__)

# Column list for DRY queries (matches row converter indices)
QUEUE_COLUMNS = """
    id, project_id, session_id, agent_type, tool_name, tool_input,
    tool_output, status, created_at, processed_at, error_message, retry_count
""".strip()


# =============================================================================
# Queue Row Conversion
# =============================================================================


def _queue_row_to_dict(row: TupleRow | tuple[Any, ...] | None) -> dict[str, Any]:
    """Convert queue row to dict."""
    if row is None:
        raise ValueError("Row cannot be None")
    return {
        "id": str(row[0]),
        "project_id": row[1],
        "session_id": row[2],
        "agent_type": row[3],
        "tool_name": row[4],
        "tool_input": row[5],
        "tool_output": row[6],
        "status": row[7],
        "created_at": row[8].isoformat() if row[8] else None,
        "processed_at": row[9].isoformat() if row[9] else None,
        "error_message": row[10],
        "retry_count": row[11],
    }


# =============================================================================
# Queue CRUD Operations
# =============================================================================


def create_queue_item(
    project_id: str,
    session_id: str,
    agent_type: str,
    tool_name: str,
    tool_input: dict[str, Any] | None = None,
    tool_output: str | None = None,
    skip_memory_check: bool = False,
) -> dict[str, Any] | None:
    """Create a queue item for async observation extraction.

    Args:
        skip_memory_check: If True, bypass the memory enabled check.

    Returns:
        The created queue item, or None if memory is disabled.
    """
    if not skip_memory_check and not is_memory_feature_enabled(project_id, "observations"):
        logger.debug(f"Memory observations disabled for {project_id}, skipping queue item")
        return None

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO observation_queue
                (project_id, session_id, agent_type, tool_name, tool_input, tool_output)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING {QUEUE_COLUMNS}
            """,
            (
                project_id,
                session_id,
                agent_type,
                tool_name,
                _json_or_default(tool_input),
                tool_output,
            ),
        )
        row = cur.fetchone()
        conn.commit()

    return _queue_row_to_dict(row)


def get_pending_queue_items(limit: int = 10) -> list[dict[str, Any]]:
    """Get pending queue items for processing."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {QUEUE_COLUMNS}
            FROM observation_queue
            WHERE status = 'pending'
            ORDER BY created_at ASC
            LIMIT %s
            """,
            (limit,),
        )
        rows = cur.fetchall()

    return [_queue_row_to_dict(row) for row in rows]


def update_queue_item_status(
    item_id: str,
    status: str,
    error_message: str | None = None,
) -> bool:
    """Update queue item status.

    Returns:
        True if updated, False if not found.
    """
    with get_connection() as conn, conn.cursor() as cur:
        if status == "processed":
            cur.execute(
                """
                UPDATE observation_queue
                SET status = %s, processed_at = NOW(), error_message = %s
                WHERE id = %s
                """,
                (status, error_message, item_id),
            )
        elif status == "failed":
            cur.execute(
                """
                UPDATE observation_queue
                SET status = %s, error_message = %s, retry_count = retry_count + 1
                WHERE id = %s
                """,
                (status, error_message, item_id),
            )
        else:
            cur.execute(
                """
                UPDATE observation_queue
                SET status = %s
                WHERE id = %s
                """,
                (status, item_id),
            )
        updated = cur.rowcount > 0
        conn.commit()

    return updated


# =============================================================================
# Queue Maintenance Operations
# =============================================================================


def archive_failed_queue_items(max_age_days: int = 14) -> int:
    """Archive (delete) failed queue items older than max_age_days.

    Args:
        max_age_days: Delete failed items older than this many days.

    Returns:
        Number of items deleted.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM observation_queue
            WHERE status = 'failed'
              AND created_at < NOW() - INTERVAL '%s days'
            """,
            (max_age_days,),
        )
        deleted = cur.rowcount
        conn.commit()

    logger.info(
        f"archive_failed_queue_items: deleted {deleted} items older than {max_age_days} days"
    )
    return deleted


def reset_stuck_queue_items(threshold_minutes: int = 60) -> int:
    """Reset stuck queue items from 'processing' back to 'pending'.

    Items stuck in 'processing' for longer than threshold_minutes are reset
    so they can be reprocessed.

    Args:
        threshold_minutes: Reset items stuck longer than this.

    Returns:
        Number of items reset.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE observation_queue
            SET status = 'pending'
            WHERE status = 'processing'
              AND created_at < NOW() - INTERVAL '%s minutes'
            """,
            (threshold_minutes,),
        )
        reset_count = cur.rowcount
        conn.commit()

    logger.info(
        f"reset_stuck_queue_items: reset {reset_count} items stuck > {threshold_minutes} minutes"
    )
    return reset_count
