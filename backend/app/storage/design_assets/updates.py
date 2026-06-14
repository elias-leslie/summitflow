"""Update operations for design assets."""

from __future__ import annotations

from typing import Any

from psycopg import sql

from .._sql import static_sql
from ..connection import get_connection
from .core import ASSET_SELECT_COLUMNS, ASSET_STATUSES, _row_to_asset


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
