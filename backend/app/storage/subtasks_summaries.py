"""Subtask summaries - handoff context isolation.

This module handles subtask summary storage and retrieval for clean
context handoff between sequential subtasks without accumulated history.
"""

from __future__ import annotations

import json
from typing import Any

from ..logging_config import get_logger
from .connection import get_connection

logger = get_logger(__name__)


def _row_to_summary_dict(row: tuple[Any, ...]) -> dict[str, Any]:
    """Convert a subtask_summaries DB row to a summary dict.

    Args:
        row: Tuple of (id, subtask_id, summary, files_modified, decisions_made, created_at)

    Returns:
        Dict representation of the summary record.
    """
    return {
        "id": row[0],
        "subtask_id": row[1],
        "summary": row[2],
        "files_modified": row[3] or [],
        "decisions_made": row[4] or [],
        "created_at": row[5].isoformat() if row[5] else None,
    }


def _upsert_summary_row(
    subtask_id: str,
    summary: str,
    files_json: str,
    decisions_json: str,
) -> tuple[Any, ...]:
    """Execute the UPSERT SQL and return the resulting row.

    Args:
        subtask_id: Full subtask table ID.
        summary: Structured summary text.
        files_json: JSON-encoded list of modified files.
        decisions_json: JSON-encoded list of decisions made.

    Returns:
        The raw DB row from the RETURNING clause.

    Raises:
        ValueError: If the insert/update returned no row.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO subtask_summaries (subtask_id, summary, files_modified, decisions_made)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (subtask_id) DO UPDATE SET
                summary = EXCLUDED.summary,
                files_modified = EXCLUDED.files_modified,
                decisions_made = EXCLUDED.decisions_made,
                created_at = NOW()
            RETURNING id, subtask_id, summary, files_modified, decisions_made, created_at
            """,
            (subtask_id, summary, files_json, decisions_json),
        )
        row = cur.fetchone()
        conn.commit()

    if not row:
        raise ValueError(f"Insert failed for subtask_id={subtask_id}")

    return row


def insert_subtask_summary(
    subtask_id: str,
    summary: str,
    files_modified: list[str] | None = None,
    decisions_made: list[str] | None = None,
) -> dict[str, Any]:
    """Insert or update a handoff summary for a subtask.

    Used to capture context at subtask completion for handoff to next subtask.
    Implements UPSERT - updates existing summary if one exists.

    Args:
        subtask_id: Full subtask table ID (e.g., "task-abc123-1.1")
        summary: Structured summary of work done, key decisions, gotchas
        files_modified: List of file paths modified during this subtask
        decisions_made: List of key decisions made during execution

    Returns:
        The created/updated summary record.
    """
    files_json = json.dumps(files_modified or [])
    decisions_json = json.dumps(decisions_made or [])
    row = _upsert_summary_row(subtask_id, summary, files_json, decisions_json)
    return _row_to_summary_dict(row)


def get_previous_summary(subtask_id: str) -> dict[str, Any] | None:
    """Get the summary for a specific subtask.

    Args:
        subtask_id: Full subtask table ID (e.g., "task-abc123-1.1")

    Returns:
        Summary record or None if not found.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, subtask_id, summary, files_modified, decisions_made, created_at
            FROM subtask_summaries
            WHERE subtask_id = %s
            """,
            (subtask_id,),
        )
        row = cur.fetchone()

    if not row:
        return None

    return _row_to_summary_dict(row)


def _fetch_handoff_rows(task_id: str, current_subtask_id: str) -> list[tuple[Any, ...]]:
    """Query all completed subtask summary rows preceding the current subtask.

    Args:
        task_id: Parent task ID.
        current_subtask_id: The subtask about to be executed (e.g., "1.2").

    Returns:
        List of raw DB rows ordered by display_order.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT ss.id, ss.subtask_id, ss.summary, ss.files_modified,
                   ss.decisions_made, ss.created_at, ts.subtask_id as short_id
            FROM subtask_summaries ss
            JOIN task_subtasks ts ON ts.id = ss.subtask_id
            WHERE ts.task_id = %s
              AND ts.passes = TRUE
              AND ts.subtask_id < %s
            ORDER BY ts.display_order
            """,
            (task_id, current_subtask_id),
        )
        return cur.fetchall()


def _aggregate_handoff_rows(
    rows: list[tuple[Any, ...]],
) -> dict[str, Any]:
    """Aggregate raw DB rows into the handoff context structure.

    Args:
        rows: Raw DB rows from _fetch_handoff_rows.

    Returns:
        Dict with previous_summaries, total_files_modified, and key_decisions.
    """
    summaries = []
    all_files: list[str] = []
    all_decisions: list[str] = []

    for row in rows:
        files = row[3] or []
        decisions = row[4] or []
        summaries.append(
            {
                "id": row[0],
                "subtask_id": row[1],
                "short_id": row[6],
                "summary": row[2],
                "files_modified": files,
                "decisions_made": decisions,
                "created_at": row[5].isoformat() if row[5] else None,
            }
        )
        all_files.extend(files)
        all_decisions.extend(decisions)

    return {
        "previous_summaries": summaries,
        "total_files_modified": list(set(all_files)),
        "key_decisions": all_decisions,
    }


def get_handoff_context(task_id: str, current_subtask_id: str) -> dict[str, Any]:
    """Build handoff context for a subtask from all previous completed subtasks.

    Returns summaries from all completed subtasks before the current one,
    providing fresh context without accumulated conversation history.

    Args:
        task_id: Parent task ID
        current_subtask_id: The subtask about to be executed (e.g., "1.2")

    Returns:
        Dict with:
            - previous_summaries: List of summary records from completed subtasks
            - total_files_modified: Aggregated list of all modified files
            - key_decisions: Aggregated list of all decisions made
    """
    rows = _fetch_handoff_rows(task_id, current_subtask_id)
    return _aggregate_handoff_rows(rows)


def get_subtask_summary(task_id: str) -> dict[str, Any]:
    """Get summary of subtask completion for a task.

    Returns:
        Dict with keys:
            - total: Total number of subtasks
            - completed: Number of subtasks with passes=True
            - next_subtask_id: ID of next incomplete subtask, or None
            - progress_percent: Completion percentage (0-100)
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE passes = TRUE) as completed,
                MIN(subtask_id) FILTER (WHERE passes = FALSE) as next_subtask_id
            FROM task_subtasks
            WHERE task_id = %s
            """,
            (task_id,),
        )
        row = cur.fetchone()

    total = row[0] if row else 0
    completed = row[1] if row else 0
    next_subtask_id = row[2] if row else None
    progress_percent = round((completed / total * 100) if total > 0 else 0, 1)

    return {
        "total": total,
        "completed": completed,
        "next_subtask_id": next_subtask_id,
        "progress_percent": progress_percent,
    }
