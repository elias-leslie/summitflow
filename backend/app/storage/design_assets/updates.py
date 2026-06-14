"""Update operations for design assets."""

from __future__ import annotations

from typing import Any

from psycopg import sql

from .._sql import static_sql
from ..connection import get_connection
from .core import ASSET_SELECT_COLUMNS, ASSET_STATUSES, _row_to_asset
from .queries import get_asset


def update_asset_status(
    project_id: str,
    asset_id: str,
    status: str,
    *,
    approved_by: str | None = None,
) -> dict[str, Any] | None:
    """Update asset status."""
    if status not in ASSET_STATUSES:
        raise ValueError(f"Invalid asset status: {status}")
    approved_at_sql = "NOW()" if status == "approved" else "NULL"
    approved_by_value = approved_by if status == "approved" else None
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            sql.SQL(
                """
            UPDATE design_assets
            SET
                status = %s,
                approved_by = %s,
                approved_at = {approved_at_sql},
                updated_at = NOW()
            WHERE project_id = %s AND asset_id = %s
            RETURNING {returning}
            """
            ).format(
                approved_at_sql=static_sql(approved_at_sql),
                returning=static_sql(ASSET_SELECT_COLUMNS),
            ),
            (status, approved_by_value, project_id, asset_id),
        )
        row = cur.fetchone()
        conn.commit()
    return _row_to_asset(row) if row else None


def set_asset_rating(
    project_id: str,
    asset_id: str,
    rating: int,
    *,
    voter_key: str,
) -> dict[str, Any] | None:
    """Set or clear the current user's star rating and return the updated asset."""
    if rating < 0 or rating > 5:
        raise ValueError(f"Invalid asset rating: {rating}")
    with get_connection() as conn, conn.cursor() as cur:
        if rating == 0:
            cur.execute(
                """
                DELETE FROM design_asset_ratings r
                USING design_assets a
                WHERE r.asset_id = a.id
                  AND a.project_id = %s
                  AND a.asset_id = %s
                  AND r.voter_key = %s
                """,
                (project_id, asset_id, voter_key),
            )
            changed = cur.rowcount > 0
        else:
            cur.execute(
                """
                INSERT INTO design_asset_ratings (asset_id, voter_key, rating)
                SELECT id, %s, %s
                FROM design_assets
                WHERE project_id = %s AND asset_id = %s
                ON CONFLICT (asset_id, voter_key)
                DO UPDATE SET rating = EXCLUDED.rating, updated_at = NOW()
                WHERE design_asset_ratings.rating IS DISTINCT FROM EXCLUDED.rating
                """,
                (voter_key, rating, project_id, asset_id),
            )
            changed = cur.rowcount > 0
        conn.commit()
    if not changed and not get_asset(project_id, asset_id, voter_key=voter_key):
        return None
    return get_asset(project_id, asset_id, voter_key=voter_key)


def delete_asset(project_id: str, asset_id: str) -> bool:
    """Delete an asset."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM design_assets WHERE project_id = %s AND asset_id = %s",
            (project_id, asset_id),
        )
        deleted = cur.rowcount > 0
        conn.commit()
    return deleted
