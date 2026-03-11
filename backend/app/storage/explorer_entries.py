"""Explorer entries storage - Core CRUD operations for explorer_entries table.

This module handles:
- CRUD operations for explorer_entries
- Querying with filters, pagination, sorting
- Statistics aggregation
- Stale entry cleanup

Per architecture: No other module should contain direct explorer DB queries.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from psycopg import sql

from .connection import get_connection
from .explorer_helpers import (
    ALLOWED_SORT_FIELDS,
    ENTRY_COLUMNS,
    build_where_clause,
    row_to_entry,
    to_iso_string,
)

# Re-export functions and constants for backwards compatibility
_row_to_entry = row_to_entry
_build_where_clause = build_where_clause
_to_iso_string = to_iso_string
_ALLOWED_SORT_FIELDS = ALLOWED_SORT_FIELDS
_ENTRY_COLUMNS = ENTRY_COLUMNS


def upsert_entries(project_id: str, entry_type: str, entries: list[dict[str, Any]]) -> int:
    """Upsert explorer entries (insert or update on conflict)."""
    if not entries:
        return 0

    now = datetime.now(UTC)
    query = """
        INSERT INTO explorer_entries (
            project_id, entry_type, path, name, health_status,
            metadata, last_scanned_at, created_at, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (project_id, entry_type, path)
        DO UPDATE SET
            name = EXCLUDED.name,
            health_status = EXCLUDED.health_status,
            metadata = explorer_entries.metadata || EXCLUDED.metadata,
            last_scanned_at = EXCLUDED.last_scanned_at,
            updated_at = EXCLUDED.updated_at
    """

    with get_connection() as conn, conn.cursor() as cur:
        for entry in entries:
            cur.execute(
                query,
                (
                    project_id,
                    entry_type,
                    entry.get("path"),
                    entry.get("name"),
                    entry.get("health_status", "unknown"),
                    json.dumps(entry.get("metadata", {})),
                    now,
                    now,
                    now,
                ),
            )
        conn.commit()
        return len(entries)


def get_entries(project_id: str, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Get explorer entries with optional filters (type, health, path, sort, dir, limit, offset)."""
    filters = filters or {}

    # Build WHERE clause
    conditions = ["ee.project_id = %s"]
    params: list[Any] = [project_id]

    if filters.get("type"):
        conditions.append("ee.entry_type = %s")
        params.append(filters["type"])

    if filters.get("health"):
        conditions.append("ee.health_status = %s")
        params.append(filters["health"])

    if filters.get("path"):
        conditions.append("ee.path LIKE %s")
        params.append(f"{filters['path']}%")

    where_clause = build_where_clause(conditions)

    # Sort and pagination
    sort_field = filters.get("sort", "path")
    if sort_field not in ALLOWED_SORT_FIELDS:
        sort_field = "path"

    sort_dir = "DESC" if filters.get("dir", "asc").lower() == "desc" else "ASC"
    limit = min(int(filters.get("limit", 1000)), 10000)
    offset = int(filters.get("offset", 0))

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            sql.SQL("""
            SELECT ee.id, ee.project_id, ee.entry_type, ee.path, ee.name, ee.health_status,
                   ee.metadata, ee.last_scanned_at, ee.created_at, ee.updated_at
            FROM explorer_entries ee
            WHERE {where_clause}
            ORDER BY {sort_field} {sort_dir}
            LIMIT %s OFFSET %s
            """).format(
                where_clause=where_clause,
                sort_field=sql.Identifier("ee", sort_field),
                sort_dir=sql.SQL(sort_dir),
            ),
            (*params, limit, offset),
        )
        rows = cur.fetchall()

        return [row_to_entry(row) for row in rows]


def get_entry(project_id: str, entry_type: str, path: str) -> dict[str, Any] | None:
    """Get a single explorer entry by type and path."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT {ENTRY_COLUMNS} FROM explorer_entries "
            "WHERE project_id = %s AND entry_type = %s AND path = %s",
            (project_id, entry_type, path),
        )
        row = cur.fetchone()
        return row_to_entry(row) if row else None


def get_entry_by_id(entry_id: int) -> dict[str, Any] | None:
    """Get a single explorer entry by ID."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT {ENTRY_COLUMNS} FROM explorer_entries WHERE id = %s",
            (entry_id,),
        )
        row = cur.fetchone()
        return row_to_entry(row) if row else None


def get_children(project_id: str, entry_type: str, parent_path: str) -> list[dict[str, Any]]:
    """Get direct children of a path (for tree navigation, immediate children only)."""
    # Normalize parent path
    if parent_path and not parent_path.endswith("/"):
        parent_path = parent_path + "/"

    with get_connection() as conn, conn.cursor() as cur:
        if not parent_path:
            query = (
                f"SELECT {ENTRY_COLUMNS} FROM explorer_entries "
                "WHERE project_id = %s AND entry_type = %s AND path NOT LIKE '%%/%%' "
                "ORDER BY path"
            )
            params: tuple[Any, ...] = (project_id, entry_type)
        else:
            query = (
                f"SELECT {ENTRY_COLUMNS} FROM explorer_entries "
                "WHERE project_id = %s AND entry_type = %s AND path LIKE %s "
                "AND path NOT LIKE %s ORDER BY path"
            )
            params = (project_id, entry_type, f"{parent_path}%", f"{parent_path}%/%")

        cur.execute(query, params)
        rows = cur.fetchall()
        return [row_to_entry(row) for row in rows]


def get_stats(project_id: str, entry_type: str | None = None) -> dict[str, Any]:
    """Get aggregated statistics for explorer entries (by_type, by_health, total, last_scanned)."""
    conditions = ["project_id = %s"]
    params: list[Any] = [project_id]
    if entry_type:
        conditions.append("entry_type = %s")
        params.append(entry_type)

    where_clause = build_where_clause(conditions)

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            sql.SQL(
                "SELECT entry_type, COUNT(*) FROM explorer_entries WHERE {where_clause} GROUP BY entry_type"
            ).format(where_clause=where_clause),
            params,
        )
        by_type = {row[0]: row[1] for row in cur.fetchall()}

        cur.execute(
            sql.SQL(
                "SELECT health_status, COUNT(*) FROM explorer_entries WHERE {where_clause} GROUP BY health_status"
            ).format(where_clause=where_clause),
            params,
        )
        by_health = {row[0]: row[1] for row in cur.fetchall()}

        cur.execute(
            sql.SQL(
                "SELECT COUNT(*), MAX(last_scanned_at) FROM explorer_entries WHERE {where_clause}"
            ).format(where_clause=where_clause),
            params,
        )
        row = cur.fetchone()
        total = row[0] if row else 0
        last_scanned = to_iso_string(row[1]) if row else None

        return {
            "by_type": by_type,
            "by_health": by_health,
            "total": total,
            "last_scanned": last_scanned,
        }


def get_type_summaries(project_id: str) -> dict[str, dict[str, Any]]:
    """Return per-entry-type totals, health counts, and last scan times."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                entry_type,
                COUNT(*) AS total,
                MAX(last_scanned_at) AS last_scanned,
                COUNT(*) FILTER (WHERE health_status = 'healthy') AS healthy_count,
                COUNT(*) FILTER (WHERE health_status = 'warning') AS warning_count,
                COUNT(*) FILTER (WHERE health_status = 'error') AS error_count,
                COUNT(*) FILTER (WHERE health_status = 'unknown') AS unknown_count
            FROM explorer_entries
            WHERE project_id = %s
            GROUP BY entry_type
            ORDER BY entry_type
            """,
            (project_id,),
        )
        rows = cur.fetchall()

    summaries: dict[str, dict[str, Any]] = {}
    for row in rows:
        summaries[row[0]] = {
            "total": row[1],
            "last_scanned": to_iso_string(row[2]),
            "by_health": {
                "healthy": row[3],
                "warning": row[4],
                "error": row[5],
                "unknown": row[6],
            },
        }
    return summaries


def get_scan_metrics(project_id: str) -> dict[str, Any]:
    """Return aggregate metrics used in scan history and overview surfaces."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                COALESCE(SUM(
                    CASE
                        WHEN entry_type = 'file'
                        AND metadata->>'complexity_score' IS NOT NULL
                        THEN (metadata->>'complexity_score')::float
                        ELSE 0
                    END
                ), 0) AS complexity,
                COUNT(*) FILTER (
                    WHERE entry_type = 'file'
                    AND metadata->>'refactor_priority' = 'high'
                ) AS high_priority_count,
                COUNT(*) FILTER (
                    WHERE entry_type = 'file'
                    AND metadata->>'refactor_priority' = 'medium'
                ) AS medium_priority_count
            FROM explorer_entries
            WHERE project_id = %s
            """,
            (project_id,),
        )
        row = cur.fetchone()

    return {
        "complexity": round(float(row[0] or 0), 2) if row else 0.0,
        "high_priority_count": int(row[1] or 0) if row else 0,
        "medium_priority_count": int(row[2] or 0) if row else 0,
    }


def delete_entries(project_id: str, entry_type: str | None = None) -> int:
    """Delete explorer entries (optionally filtered by entry_type)."""
    with get_connection() as conn, conn.cursor() as cur:
        if entry_type:
            query = "DELETE FROM explorer_entries WHERE project_id = %s AND entry_type = %s"
            params: tuple[Any, ...] = (project_id, entry_type)
        else:
            query = "DELETE FROM explorer_entries WHERE project_id = %s"
            params = (project_id,)

        cur.execute(query, params)
        deleted: int = cur.rowcount or 0
        conn.commit()
        return deleted


def cleanup_stale_entries(project_id: str, entry_type: str, current_paths: set[str]) -> int:
    """Delete explorer entries that no longer exist in the codebase.

    The Explorer represents a current-state snapshot, NOT historical accumulation.
    This function removes entries for paths not found in the current scan.
    """
    if not current_paths:
        # Safety: if scan returned nothing, don't delete everything
        return 0

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT path FROM explorer_entries WHERE project_id = %s AND entry_type = %s",
            (project_id, entry_type),
        )
        existing_paths = {row[0] for row in cur.fetchall()}

        stale_paths = existing_paths - current_paths
        if not stale_paths:
            return 0

        cur.execute(
            "DELETE FROM explorer_entries WHERE project_id = %s AND entry_type = %s "
            "AND path = ANY(%s)",
            (project_id, entry_type, list(stale_paths)),
        )
        deleted: int = cur.rowcount or 0
        conn.commit()
        return deleted


def update_health_check(entry_id: int, health_status: str, health_data: dict[str, Any]) -> bool:
    """Update health check data for an explorer entry."""
    from psycopg.types.json import Jsonb

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE explorer_entries SET health_status = %s, metadata = metadata || %s, "
            "updated_at = NOW() WHERE id = %s RETURNING id",
            (health_status, Jsonb(health_data), entry_id),
        )
        row = cur.fetchone()
        conn.commit()
        return row is not None


def get_pages_for_health_check(project_id: str) -> list[dict[str, Any]]:
    """Get page entries that need health checks."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT {ENTRY_COLUMNS} FROM explorer_entries "
            "WHERE project_id = %s AND entry_type = 'page' ORDER BY path",
            (project_id,),
        )
        rows = cur.fetchall()
        return [row_to_entry(row) for row in rows]
