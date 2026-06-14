"""Read operations for design assets."""

from __future__ import annotations

from typing import Any

from psycopg import sql

from .._sql import join_static_sql, static_sql
from ..connection import get_cursor
from .core import (
    ASSET_COMMENT_COUNT_SELECT_COLUMN,
    ASSET_RATING_SELECT_COLUMNS,
    ASSET_SELECT_COLUMNS_ALIASED,
    _row_to_asset,
    _row_to_export,
)

_ASSET_RATING_JOIN_SQL = """
LEFT JOIN (
    SELECT
        asset_id,
        AVG(rating)::float AS rating_average,
        COUNT(*) AS rating_count
    FROM design_asset_ratings
    GROUP BY asset_id
) rating_counts ON rating_counts.asset_id = a.id
LEFT JOIN design_asset_ratings user_rating
    ON user_rating.asset_id = a.id AND user_rating.voter_key = %s
"""

_ASSET_COMMENT_COUNT_JOIN_SQL = """
LEFT JOIN (
    SELECT asset_id, COUNT(*) AS comment_count
    FROM design_asset_comments
    GROUP BY asset_id
) comment_counts ON comment_counts.asset_id = a.id
"""

_ASSET_SORT_SQL = {
    "created_desc": "a.created_at DESC",
    "rating_average": "rating_average DESC, rating_count DESC, a.created_at DESC",
    "rating_count": "rating_count DESC, rating_average DESC, a.created_at DESC",
}


def get_asset(
    project_id: str,
    asset_id: str,
    *,
    voter_key: str | None = None,
) -> dict[str, Any] | None:
    """Get a single asset."""
    with get_cursor() as cur:
        cur.execute(
            static_sql(
                f"""
                SELECT {ASSET_SELECT_COLUMNS_ALIASED}, {ASSET_RATING_SELECT_COLUMNS},
                       {ASSET_COMMENT_COUNT_SELECT_COLUMN}
                FROM design_assets a
                {_ASSET_RATING_JOIN_SQL}
                {_ASSET_COMMENT_COUNT_JOIN_SQL}
                WHERE a.project_id = %s AND a.asset_id = %s
                """
            ),
            (voter_key or "", project_id, asset_id),
        )
        row = cur.fetchone()
    return _row_to_asset(row) if row else None


def list_assets(
    project_id: str,
    *,
    limit: int = 100,
    offset: int = 0,
    asset_type: str | None = None,
    workflow: str | None = None,
    status: str | None = None,
    search: str | None = None,
    tag: str | None = None,
    sort_by: str = "created_desc",
    voter_key: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """List assets with filters."""
    clauses = ["a.project_id = %s"]
    params: list[Any] = [project_id]

    if asset_type:
        clauses.append("a.asset_type = %s")
        params.append(asset_type)
    if workflow:
        clauses.append("a.workflow = %s")
        params.append(workflow)
    if status:
        clauses.append("a.status = %s")
        params.append(status)
    if search:
        clauses.append("(a.name ILIKE %s OR a.description ILIKE %s OR a.prompt ILIKE %s)")
        pattern = f"%{search}%"
        params.extend([pattern, pattern, pattern])
    if tag:
        clauses.append("%s = ANY(a.tags)")
        params.append(tag)

    order_by = _ASSET_SORT_SQL.get(sort_by)
    if order_by is None:
        raise ValueError(f"Invalid asset sort: {sort_by}")

    where_sql = join_static_sql(clauses, " AND ")
    with get_cursor() as cur:
        cur.execute(
            static_sql("SELECT COUNT(*) FROM design_assets a WHERE ") + where_sql,
            params,
        )
        total_row = cur.fetchone()
        total = int(total_row[0]) if total_row and total_row[0] else 0

        cur.execute(
            static_sql(
                f"""
                SELECT {ASSET_SELECT_COLUMNS_ALIASED}, {ASSET_RATING_SELECT_COLUMNS},
                       {ASSET_COMMENT_COUNT_SELECT_COLUMN}
                FROM design_assets a
                {_ASSET_RATING_JOIN_SQL}
                {_ASSET_COMMENT_COUNT_JOIN_SQL}
                WHERE
                """
            )
            + where_sql
            + sql.SQL(" ORDER BY ")
            + static_sql(order_by)
            + sql.SQL(" LIMIT %s OFFSET %s"),
            [voter_key or "", *params, limit, offset],
        )
        rows = cur.fetchall()
    return [_row_to_asset(row) for row in rows], total


def list_asset_exports(project_id: str, asset_id: str) -> list[dict[str, Any]]:
    """List exports for an asset."""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT
                e.id,
                e.asset_id,
                e.export_id,
                e.export_type,
                e.file_path,
                e.manifest_path,
                e.metadata,
                e.created_at
            FROM design_asset_exports e
            JOIN design_assets a ON a.id = e.asset_id
            WHERE a.project_id = %s AND a.asset_id = %s
            ORDER BY e.created_at DESC
            """,
            (project_id, asset_id),
        )
        rows = cur.fetchall()
    return [_row_to_export(row) for row in rows]


def get_asset_stats(project_id: str) -> dict[str, Any]:
    """Aggregate stats for assets."""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE status = 'generated') AS generated,
                COUNT(*) FILTER (WHERE status = 'approved') AS approved,
                COUNT(*) FILTER (WHERE status = 'rejected') AS rejected,
                COUNT(*) FILTER (WHERE status = 'archived') AS archived,
                COUNT(*) FILTER (WHERE status = 'exported') AS exported,
                COUNT(*) FILTER (WHERE asset_type = 'sprite') AS sprites,
                COUNT(*) FILTER (WHERE asset_type = 'sprite_sheet') AS sheets,
                COUNT(*) FILTER (WHERE asset_type = 'environment') AS environments,
                COUNT(DISTINCT model) AS unique_models
            FROM design_assets
            WHERE project_id = %s
            """,
            (project_id,),
        )
        row = cur.fetchone()

    if not row:
        return {
            "total": 0,
            "by_status": {},
            "by_type": {},
            "unique_models": 0,
        }
    return {
        "total": int(row[0] or 0),
        "by_status": {
            "generated": int(row[1] or 0),
            "approved": int(row[2] or 0),
            "rejected": int(row[3] or 0),
            "archived": int(row[4] or 0),
            "exported": int(row[5] or 0),
        },
        "by_type": {
            "sprite": int(row[6] or 0),
            "sprite_sheet": int(row[7] or 0),
            "environment": int(row[8] or 0),
        },
        "unique_models": int(row[9] or 0),
    }
