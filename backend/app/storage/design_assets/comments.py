"""Comment operations for design assets."""

from __future__ import annotations

from typing import Any

from ..connection import get_connection, get_cursor

_COMMENT_SELECT_COLUMNS = "c.id, c.author_email, c.body, c.created_at, c.updated_at"
_MAX_COMMENT_LENGTH = 4000


def _clean_body(body: str) -> str:
    cleaned = body.strip()
    if not cleaned:
        raise ValueError("Comment cannot be empty")
    if len(cleaned) > _MAX_COMMENT_LENGTH:
        raise ValueError("Comment is too long")
    return cleaned


def _row_to_comment(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "id": row[0],
        "author_email": row[1],
        "body": row[2],
        "created_at": row[3].isoformat() if row[3] else None,
        "updated_at": row[4].isoformat() if row[4] else None,
    }


def list_asset_comments(project_id: str, asset_id: str) -> list[dict[str, Any]]:
    """List comments for one design asset."""
    with get_cursor() as cur:
        cur.execute(
            f"""
            SELECT {_COMMENT_SELECT_COLUMNS}
            FROM design_asset_comments c
            JOIN design_assets a ON a.id = c.asset_id
            WHERE a.project_id = %s AND a.asset_id = %s
            ORDER BY c.created_at ASC, c.id ASC
            """,
            (project_id, asset_id),
        )
        rows = cur.fetchall()
    return [_row_to_comment(row) for row in rows]


def create_asset_comment(
    project_id: str,
    asset_id: str,
    body: str,
    *,
    author_email: str,
) -> dict[str, Any] | None:
    """Create a comment for one design asset."""
    cleaned = _clean_body(body)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO design_asset_comments (asset_id, author_email, body)
            SELECT id, %s, %s
            FROM design_assets
            WHERE project_id = %s AND asset_id = %s
            RETURNING id, author_email, body, created_at, updated_at
            """,
            (author_email, cleaned, project_id, asset_id),
        )
        row = cur.fetchone()
        conn.commit()
    return _row_to_comment(row) if row else None


def update_asset_comment(
    project_id: str,
    asset_id: str,
    comment_id: int,
    body: str,
    *,
    author_email: str,
) -> dict[str, Any] | None:
    """Update one of the current user's asset comments."""
    cleaned = _clean_body(body)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE design_asset_comments c
            SET body = %s, updated_at = NOW()
            FROM design_assets a
            WHERE c.asset_id = a.id
              AND a.project_id = %s
              AND a.asset_id = %s
              AND c.id = %s
              AND c.author_email = %s
            RETURNING {_COMMENT_SELECT_COLUMNS}
            """,
            (cleaned, project_id, asset_id, comment_id, author_email),
        )
        row = cur.fetchone()
        conn.commit()
    return _row_to_comment(row) if row else None


def delete_asset_comment(
    project_id: str,
    asset_id: str,
    comment_id: int,
    *,
    author_email: str,
) -> bool:
    """Delete one of the current user's asset comments."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM design_asset_comments c
            USING design_assets a
            WHERE c.asset_id = a.id
              AND a.project_id = %s
              AND a.asset_id = %s
              AND c.id = %s
              AND c.author_email = %s
            """,
            (project_id, asset_id, comment_id, author_email),
        )
        deleted = cur.rowcount > 0
        conn.commit()
    return deleted
