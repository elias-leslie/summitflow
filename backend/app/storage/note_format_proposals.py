"""Note format proposals — background formatting results persisted to DB."""

from __future__ import annotations

from typing import Any

from psycopg import sql

from ._sql import static_sql
from .connection import generate_prefixed_id, get_connection, get_cursor

_RETURNING_COLS = """
    id, note_id, status, original_title, original_content,
    proposed_title, proposed_content, error_message, created_at, completed_at
"""

_SELECT_COLS = f"SELECT {_RETURNING_COLS} FROM note_format_proposals"


def _row_to_dict(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "id": row[0],
        "note_id": row[1],
        "status": row[2],
        "original_title": row[3],
        "original_content": row[4],
        "proposed_title": row[5],
        "proposed_content": row[6],
        "error_message": row[7],
        "created_at": row[8],
        "completed_at": row[9],
    }


def create_proposal(
    note_id: str,
    original_title: str,
    original_content: str,
) -> dict[str, Any]:
    """Create a pending format proposal. Returns the proposal dict."""
    proposal_id = generate_prefixed_id("nfmt")
    with get_connection() as conn, conn.cursor() as cur:
        # Cancel any existing pending proposals for this note
        cur.execute(
            "UPDATE note_format_proposals SET status = 'discarded' WHERE note_id = %s AND status = 'pending'",
            (note_id,),
        )
        cur.execute(
            sql.SQL(
                """
            INSERT INTO note_format_proposals (id, note_id, status, original_title, original_content)
            VALUES (%s, %s, 'pending', %s, %s)
            RETURNING {returning}
            """
            ).format(returning=static_sql(_RETURNING_COLS)),
            (proposal_id, note_id, original_title, original_content),
        )
        result = cur.fetchone()
        conn.commit()
    if result is None:
        raise RuntimeError("Failed to create note format proposal")
    return _row_to_dict(result)


def complete_proposal(
    proposal_id: str,
    proposed_title: str,
    proposed_content: str,
) -> dict[str, Any] | None:
    """Mark a proposal as complete with the formatted result."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE note_format_proposals
            SET status = 'complete', proposed_title = %s, proposed_content = %s, completed_at = NOW()
            WHERE id = %s AND status = 'pending'
            RETURNING id, note_id, status, original_title, original_content,
                      proposed_title, proposed_content, error_message, created_at, completed_at
            """,
            (proposed_title, proposed_content, proposal_id),
        )
        result = cur.fetchone()
        conn.commit()
    return _row_to_dict(result) if result else None


def fail_proposal(proposal_id: str, error_message: str) -> None:
    """Mark a proposal as failed."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE note_format_proposals SET status = 'failed', error_message = %s, completed_at = NOW() WHERE id = %s",
            (error_message, proposal_id),
        )
        conn.commit()


def resolve_proposal(proposal_id: str, status: str) -> None:
    """Mark a proposal as accepted or discarded."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE note_format_proposals SET status = %s WHERE id = %s",
            (status, proposal_id),
        )
        conn.commit()


def get_latest_proposal(note_id: str) -> dict[str, Any] | None:
    """Get the most recent pending or complete proposal for a note."""
    with get_cursor() as cur:
        cur.execute(
            f"{_SELECT_COLS} WHERE note_id = %s AND status IN ('pending', 'complete') ORDER BY created_at DESC LIMIT 1",
            (note_id,),
        )
        row = cur.fetchone()
    return _row_to_dict(row) if row else None
