"""Update operations for design assets."""

from __future__ import annotations

from typing import Any

from psycopg import sql

from .._sql import static_sql
from ..connection import get_connection
from .core import ASSET_SELECT_COLUMNS, ASSET_STATUSES, _row_to_asset
from .queries import get_asset

ASSET_VOTES = frozenset({"up", "down"})


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


def create_asset_vote(
    project_id: str,
    asset_id: str,
    vote: str,
    *,
    voter_email: str | None = None,
) -> dict[str, Any] | None:
    """Add one cumulative vote to an asset and return the updated asset."""
    if vote not in ASSET_VOTES:
        raise ValueError(f"Invalid asset vote: {vote}")
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO design_asset_votes (asset_id, vote, voter_email)
            SELECT id, %s, %s
            FROM design_assets
            WHERE project_id = %s AND asset_id = %s
            """,
            (vote, voter_email, project_id, asset_id),
        )
        created = cur.rowcount > 0
        conn.commit()
    if not created:
        return None
    return get_asset(project_id, asset_id)


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
