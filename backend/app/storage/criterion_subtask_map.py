"""Criterion-Subtask Map storage - Links criteria to implementing subtasks.

Handles the criterion_subtask_map junction table which tracks which
subtask(s) implement which acceptance criteria.
"""

from __future__ import annotations

import logging
from typing import Any

from psycopg.rows import TupleRow

from .connection import get_connection

logger = logging.getLogger(__name__)

# Expected columns for validation
EXPECTED_COLUMNS = 4  # criterion_id, subtask_id, is_primary, created_at


def _row_to_dict(row: TupleRow | tuple[Any, ...] | None) -> dict[str, Any] | None:
    """Convert a criterion_subtask_map row to a dictionary."""
    if row is None:
        return None
    if len(row) != EXPECTED_COLUMNS:
        raise ValueError(
            f"Expected {EXPECTED_COLUMNS} columns for criterion_subtask_map, got {len(row)}"
        )
    return {
        "criterion_id": row[0],
        "subtask_id": row[1],
        "is_primary": row[2],
        "created_at": row[3].isoformat() if row[3] else None,
    }


def link_criterion_to_subtask(
    criterion_id: int,
    subtask_id: str,
    is_primary: bool = False,
) -> dict[str, Any] | None:
    """Link a criterion to a subtask.

    Args:
        criterion_id: The criterion ID (from task_acceptance_criteria.id)
        subtask_id: The subtask ID (from task_subtasks.id)
        is_primary: Whether this subtask is the primary implementer

    Returns:
        Created mapping or None if already exists
    """
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO criterion_subtask_map (criterion_id, subtask_id, is_primary)
            VALUES (%s, %s, %s)
            ON CONFLICT (criterion_id, subtask_id) DO UPDATE SET
                is_primary = EXCLUDED.is_primary
            RETURNING *
            """,
            (criterion_id, subtask_id, is_primary),
        )
        row = cur.fetchone()
        conn.commit()
        if row:
            logger.info(
                f"Linked criterion {criterion_id} to subtask {subtask_id} (primary={is_primary})"
            )
        return _row_to_dict(row)


def unlink_criterion_from_subtask(criterion_id: int, subtask_id: str) -> bool:
    """Remove a criterion-subtask link.

    Args:
        criterion_id: The criterion ID
        subtask_id: The subtask ID

    Returns:
        True if deleted, False if not found
    """
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            DELETE FROM criterion_subtask_map
            WHERE criterion_id = %s AND subtask_id = %s
            """,
            (criterion_id, subtask_id),
        )
        deleted = cur.rowcount > 0
        conn.commit()
        if deleted:
            logger.info(f"Unlinked criterion {criterion_id} from subtask {subtask_id}")
        return deleted


def get_subtasks_for_criterion(criterion_id: int) -> list[dict[str, Any]]:
    """Get all subtasks that implement a criterion.

    Args:
        criterion_id: The criterion ID

    Returns:
        List of subtask info including the mapping metadata
    """
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT csm.criterion_id, csm.subtask_id, csm.is_primary, csm.created_at,
                   ts.description, ts.passes, ts.phase
            FROM criterion_subtask_map csm
            JOIN task_subtasks ts ON csm.subtask_id = ts.id
            WHERE csm.criterion_id = %s
            ORDER BY csm.is_primary DESC, ts.display_order
            """,
            (criterion_id,),
        )
        return [
            {
                "criterion_id": row[0],
                "subtask_id": row[1],
                "is_primary": row[2],
                "created_at": row[3].isoformat() if row[3] else None,
                "description": row[4],
                "passes": row[5],
                "phase": row[6],
            }
            for row in cur.fetchall()
        ]


def get_criteria_for_subtask(subtask_id: str) -> list[dict[str, Any]]:
    """Get all criteria that a subtask implements.

    Args:
        subtask_id: The subtask ID

    Returns:
        List of criterion info including the mapping metadata
    """
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT csm.criterion_id, csm.subtask_id, csm.is_primary, csm.created_at,
                   tac.criterion_id as criterion_code, tac.criterion, tac.verified
            FROM criterion_subtask_map csm
            JOIN task_acceptance_criteria tac ON csm.criterion_id = tac.id
            WHERE csm.subtask_id = %s
            ORDER BY csm.is_primary DESC, tac.display_order
            """,
            (subtask_id,),
        )
        return [
            {
                "db_id": row[0],
                "subtask_id": row[1],
                "is_primary": row[2],
                "created_at": row[3].isoformat() if row[3] else None,
                "criterion_id": row[4],
                "criterion": row[5],
                "verified": row[6],
            }
            for row in cur.fetchall()
        ]


def get_primary_subtask_for_criterion(criterion_id: int) -> str | None:
    """Get the primary subtask for a criterion.

    Args:
        criterion_id: The criterion ID

    Returns:
        The subtask ID or None if no primary is set
    """
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT subtask_id
            FROM criterion_subtask_map
            WHERE criterion_id = %s AND is_primary = TRUE
            LIMIT 1
            """,
            (criterion_id,),
        )
        row = cur.fetchone()
        return row[0] if row else None


def set_primary_subtask(criterion_id: int, subtask_id: str) -> bool:
    """Set a subtask as the primary implementer of a criterion.

    Clears any existing primary and sets the new one.

    Args:
        criterion_id: The criterion ID
        subtask_id: The subtask ID to make primary

    Returns:
        True if updated, False if link doesn't exist
    """
    with get_connection() as conn:
        cur = conn.cursor()
        # Clear existing primary
        cur.execute(
            """
            UPDATE criterion_subtask_map
            SET is_primary = FALSE
            WHERE criterion_id = %s AND is_primary = TRUE
            """,
            (criterion_id,),
        )
        # Set new primary
        cur.execute(
            """
            UPDATE criterion_subtask_map
            SET is_primary = TRUE
            WHERE criterion_id = %s AND subtask_id = %s
            """,
            (criterion_id, subtask_id),
        )
        updated = cur.rowcount > 0
        conn.commit()
        if updated:
            logger.info(f"Set subtask {subtask_id} as primary for criterion {criterion_id}")
        return updated


def bulk_link_criteria(
    mappings: list[tuple[int, str, bool]],
) -> list[dict[str, Any]]:
    """Link multiple criteria to subtasks at once.

    Args:
        mappings: List of (criterion_id, subtask_id, is_primary) tuples

    Returns:
        List of created/updated mappings
    """
    if not mappings:
        return []

    with get_connection() as conn:
        cur = conn.cursor()
        cur.executemany(
            """
            INSERT INTO criterion_subtask_map (criterion_id, subtask_id, is_primary)
            VALUES (%s, %s, %s)
            ON CONFLICT (criterion_id, subtask_id) DO UPDATE SET
                is_primary = EXCLUDED.is_primary
            """,
            mappings,
        )
        conn.commit()

        # Query back what we inserted
        if mappings:
            placeholders = ", ".join("(%s, %s)" for _ in mappings)
            flat_values = [v for m in mappings for v in (m[0], m[1])]
            cur.execute(
                f"""
                SELECT * FROM criterion_subtask_map
                WHERE (criterion_id, subtask_id) IN ({placeholders})
                """,
                flat_values,
            )
            return [r for r in [_row_to_dict(row) for row in cur.fetchall()] if r is not None]
        return []


def delete_mappings_for_subtask(subtask_id: str) -> int:
    """Delete all criterion mappings for a subtask.

    Args:
        subtask_id: The subtask ID

    Returns:
        Number of mappings deleted
    """
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM criterion_subtask_map WHERE subtask_id = %s",
            (subtask_id,),
        )
        deleted = cur.rowcount
        conn.commit()
        if deleted:
            logger.info(f"Deleted {deleted} criterion mappings for subtask {subtask_id}")
        return deleted


def delete_mappings_for_criterion(criterion_id: int) -> int:
    """Delete all subtask mappings for a criterion.

    Args:
        criterion_id: The criterion ID

    Returns:
        Number of mappings deleted
    """
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM criterion_subtask_map WHERE criterion_id = %s",
            (criterion_id,),
        )
        deleted = cur.rowcount
        conn.commit()
        if deleted:
            logger.info(f"Deleted {deleted} subtask mappings for criterion {criterion_id}")
        return deleted
