"""Mockups updates - Update operations and status transitions."""

from __future__ import annotations

from typing import Any

from psycopg.types.json import Jsonb

from .._sql import static_sql
from ..connection import get_connection
from .core import MOCKUP_SELECT_COLUMNS, MOCKUP_STATUSES, _row_to_mockup
from .queries import get_mockup


def update_mockup(
    project_id: str,
    mockup_id: str,
    *,
    name: str | None = None,
    description: str | None = None,
    file_path: str | None = None,
    content: str | None = None,
    page_path: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Update mockup fields.

    Only allows updating non-provenance fields.
    """
    updates = []
    params: list[Any] = []

    if name is not None:
        updates.append("name = %s")
        params.append(name)

    if description is not None:
        updates.append("description = %s")
        params.append(description)

    if file_path is not None:
        updates.append("file_path = %s")
        params.append(file_path)

    if content is not None:
        updates.append("content = %s")
        params.append(content)

    if page_path is not None:
        updates.append("page_path = %s")
        params.append(page_path)

    if metadata is not None:
        updates.append("metadata = %s")
        params.append(Jsonb(metadata))

    if not updates:
        return get_mockup(project_id, mockup_id)

    params.extend([project_id, mockup_id])

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            static_sql(
                f"""
                UPDATE mockups
                SET {", ".join(updates)}
                WHERE project_id = %s AND mockup_id = %s
                RETURNING {MOCKUP_SELECT_COLUMNS}
                """
            ),
            params,
        )
        row = cur.fetchone()
        conn.commit()

        if not row:
            return None

        return _row_to_mockup(row)


def update_mockup_status(
    project_id: str,
    mockup_id: str,
    status: str,
    *,
    approved_by: str | None = None,
) -> dict[str, Any] | None:
    """Update mockup status.

    Args:
        project_id: Project ID
        mockup_id: Mockup ID
        status: New status
        approved_by: Who approved (required if status is 'approved')
    """
    if status not in MOCKUP_STATUSES:
        raise ValueError(f"Invalid status: {status}. Must be one of {MOCKUP_STATUSES}")

    with get_connection() as conn, conn.cursor() as cur:
        if status == "approved":
            cur.execute(
                static_sql(
                    f"""
                UPDATE mockups
                SET status = %s, approved_at = NOW(), approved_by = %s, applied_at = NULL
                WHERE project_id = %s AND mockup_id = %s
                RETURNING {MOCKUP_SELECT_COLUMNS}
                """
                ),
                (status, approved_by, project_id, mockup_id),
            )
        elif status == "applied":
            cur.execute(
                static_sql(
                    f"""
                UPDATE mockups
                SET status = %s, applied_at = NOW()
                WHERE project_id = %s AND mockup_id = %s
                RETURNING {MOCKUP_SELECT_COLUMNS}
                """
                ),
                (status, project_id, mockup_id),
            )
        else:
            cur.execute(
                static_sql(
                    f"""
                UPDATE mockups
                SET status = %s, approved_at = NULL, approved_by = NULL, applied_at = NULL
                WHERE project_id = %s AND mockup_id = %s
                RETURNING {MOCKUP_SELECT_COLUMNS}
                """
                ),
                (status, project_id, mockup_id),
            )
        row = cur.fetchone()
        conn.commit()

        if not row:
            return None

        return _row_to_mockup(row)


def set_mockup_rating(
    project_id: str,
    mockup_id: str,
    rating: int,
    *,
    voter_key: str,
) -> dict[str, Any] | None:
    """Set or clear the current user's star rating and return the updated mockup."""
    if rating < 0 or rating > 5:
        raise ValueError(f"Invalid mockup rating: {rating}")
    with get_connection() as conn, conn.cursor() as cur:
        if rating == 0:
            cur.execute(
                """
                DELETE FROM mockup_ratings r
                USING mockups m
                WHERE r.mockup_id = m.id
                  AND m.project_id = %s
                  AND m.mockup_id = %s
                  AND r.voter_key = %s
                """,
                (project_id, mockup_id, voter_key),
            )
            changed = cur.rowcount > 0
        else:
            cur.execute(
                """
                INSERT INTO mockup_ratings (mockup_id, voter_key, rating)
                SELECT id, %s, %s
                FROM mockups
                WHERE project_id = %s AND mockup_id = %s
                ON CONFLICT (mockup_id, voter_key)
                DO UPDATE SET rating = EXCLUDED.rating, updated_at = NOW()
                WHERE mockup_ratings.rating IS DISTINCT FROM EXCLUDED.rating
                """,
                (voter_key, rating, project_id, mockup_id),
            )
            changed = cur.rowcount > 0
        conn.commit()
    if not changed and not get_mockup(project_id, mockup_id, voter_key=voter_key):
        return None
    return get_mockup(project_id, mockup_id, voter_key=voter_key)


def delete_mockup(project_id: str, mockup_id: str) -> bool:
    """Delete a mockup by project_id and mockup_id.

    Returns:
        True if deleted, False if not found
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM mockups WHERE project_id = %s AND mockup_id = %s RETURNING id",
            (project_id, mockup_id),
        )
        row = cur.fetchone()
        conn.commit()

        return row is not None


def archive_mockup(project_id: str, mockup_id: str) -> dict[str, Any] | None:
    """Archive a mockup (soft delete by setting status to 'archived')."""
    return update_mockup_status(project_id, mockup_id, "archived")
