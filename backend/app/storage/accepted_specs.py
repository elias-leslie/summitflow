"""Accepted specs storage layer - Permanent spec storage.

This module provides data access for permanently saved spec definitions.
Specs are saved here when a user accepts a generated spec from a roundtable session.
"""

from __future__ import annotations

from typing import Any

from .connection import get_connection


def save_accepted_spec(
    project_id: str,
    spec_json: dict[str, Any],
    accepted_by: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Save an accepted spec to permanent storage.

    Args:
        project_id: Project ID
        spec_json: The spec JSON (components, capabilities, tests)
        accepted_by: Who accepted the spec ('user', agent name, etc.)
        notes: Optional notes

    Returns:
        The created spec record dict.
    """
    import json

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO accepted_specs (project_id, spec_json, accepted_by, notes)
            VALUES (%s, %s, %s, %s)
            RETURNING id, project_id, spec_json, accepted_at, accepted_by, notes, created_at
            """,
            (project_id, json.dumps(spec_json), accepted_by, notes),
        )
        row = cur.fetchone()
        conn.commit()

    return _row_to_dict(row)


def get_accepted_spec(spec_id: int) -> dict[str, Any] | None:
    """Get an accepted spec by ID.

    Args:
        spec_id: The spec ID (database ID)

    Returns:
        Spec dict or None if not found.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, project_id, spec_json, accepted_at, accepted_by, notes, created_at
            FROM accepted_specs
            WHERE id = %s
            """,
            (spec_id,),
        )
        row = cur.fetchone()

    return _row_to_dict(row) if row else None


def list_accepted_specs(
    project_id: str,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """List accepted specs for a project.

    Args:
        project_id: Project ID
        limit: Maximum number of specs to return (default 10)

    Returns:
        List of spec dicts, ordered by accepted_at DESC.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, project_id, spec_json, accepted_at, accepted_by, notes, created_at
            FROM accepted_specs
            WHERE project_id = %s
            ORDER BY accepted_at DESC
            LIMIT %s
            """,
            (project_id, limit),
        )
        rows = cur.fetchall()

    return [_row_to_dict(row) for row in rows]


def get_latest_accepted_spec(project_id: str) -> dict[str, Any] | None:
    """Get the most recent accepted spec for a project.

    Args:
        project_id: Project ID

    Returns:
        Spec dict or None if no specs exist.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, project_id, spec_json, accepted_at, accepted_by, notes, created_at
            FROM accepted_specs
            WHERE project_id = %s
            ORDER BY accepted_at DESC
            LIMIT 1
            """,
            (project_id,),
        )
        row = cur.fetchone()

    return _row_to_dict(row) if row else None


def delete_accepted_spec(spec_id: int) -> bool:
    """Delete an accepted spec by ID.

    Args:
        spec_id: The spec ID to delete

    Returns:
        True if deleted, False if not found.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM accepted_specs
            WHERE id = %s
            RETURNING id
            """,
            (spec_id,),
        )
        row = cur.fetchone()
        conn.commit()

    return row is not None


def _row_to_dict(row: tuple | None) -> dict[str, Any]:
    """Convert a database row to a dict."""
    if row is None:
        return {}

    return {
        "id": row[0],
        "project_id": row[1],
        "spec_json": row[2],  # psycopg3 auto-converts JSONB to dict
        "accepted_at": row[3].isoformat() if row[3] else None,
        "accepted_by": row[4],
        "notes": row[5],
        "created_at": row[6].isoformat() if row[6] else None,
    }
