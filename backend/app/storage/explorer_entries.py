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

# Re-export constants for backwards compatibility
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
    """Get direct children of a path (for tree navigation).

    For files: returns entries where path starts with parent_path/ and has no
    additional slashes (immediate children only).

    Args:
        project_id: Project ID for scoping
        entry_type: Entry type
        parent_path: Parent path to find children of

    Returns:
        List of child entry dicts
    """
    # Normalize parent path
    if parent_path and not parent_path.endswith("/"):
        parent_path = parent_path + "/"

    with get_connection() as conn, conn.cursor() as cur:
        if not parent_path:
            # Root level - find top-level entries
            cur.execute(
                f"""
                SELECT {_ENTRY_COLUMNS}
                FROM explorer_entries
                WHERE project_id = %s
                  AND entry_type = %s
                  AND path NOT LIKE '%%/%%'
                ORDER BY path
                """,
                (project_id, entry_type),
            )
        else:
            # Find immediate children of parent_path
            cur.execute(
                f"""
                SELECT {_ENTRY_COLUMNS}
                FROM explorer_entries
                WHERE project_id = %s
                  AND entry_type = %s
                  AND path LIKE %s
                  AND path NOT LIKE %s
                ORDER BY path
                """,
                (
                    project_id,
                    entry_type,
                    f"{parent_path}%",
                    f"{parent_path}%/%",
                ),
            )

        rows = cur.fetchall()
        return [_row_to_entry(row) for row in rows]


def get_stats(project_id: str, entry_type: str | None = None) -> dict[str, Any]:
    """Get aggregated statistics for explorer entries.

    Args:
        project_id: Project ID for scoping
        entry_type: Optional entry type to filter stats by

    Returns:
        Dict with:
            - by_type: {type: count}
            - by_health: {health: count}
            - total: total count
            - last_scanned: most recent scan timestamp
    """
    # Build WHERE clause using parameterized conditions
    conditions = ["project_id = %s"]
    params: list[Any] = [project_id]
    if entry_type:
        conditions.append("entry_type = %s")
        params.append(entry_type)

    where_clause = _build_where_clause(conditions)

    with get_connection() as conn, conn.cursor() as cur:
        # Count by type
        cur.execute(
            sql.SQL("""
            SELECT entry_type, COUNT(*) as count
            FROM explorer_entries
            WHERE {where_clause}
            GROUP BY entry_type
            """).format(where_clause=where_clause),
            params,
        )
        by_type = {row[0]: row[1] for row in cur.fetchall()}

        # Count by health
        cur.execute(
            sql.SQL("""
            SELECT health_status, COUNT(*) as count
            FROM explorer_entries
            WHERE {where_clause}
            GROUP BY health_status
            """).format(where_clause=where_clause),
            params,
        )
        by_health = {row[0]: row[1] for row in cur.fetchall()}

        # Total and last scanned
        cur.execute(
            sql.SQL("""
            SELECT COUNT(*), MAX(last_scanned_at)
            FROM explorer_entries
            WHERE {where_clause}
            """).format(where_clause=where_clause),
            params,
        )
        row = cur.fetchone()
        total = row[0] if row else 0
        last_scanned = _to_iso_string(row[1]) if row else None

        return {
            "by_type": by_type,
            "by_health": by_health,
            "total": total,
            "last_scanned": last_scanned,
        }


def delete_entries(project_id: str, entry_type: str | None = None) -> int:
    """Delete explorer entries.

    Args:
        project_id: Project ID for scoping
        entry_type: Optional entry type to filter (deletes all types if None)

    Returns:
        Number of entries deleted
    """
    with get_connection() as conn, conn.cursor() as cur:
        if entry_type:
            cur.execute(
                """
                DELETE FROM explorer_entries
                WHERE project_id = %s AND entry_type = %s
                """,
                (project_id, entry_type),
            )
        else:
            cur.execute(
                """
                DELETE FROM explorer_entries
                WHERE project_id = %s
                """,
                (project_id,),
            )

        deleted: int = cur.rowcount or 0
        conn.commit()
        return deleted


def cleanup_stale_entries(project_id: str, entry_type: str, current_paths: set[str]) -> int:
    """Delete explorer entries that no longer exist in the codebase.

    ARCHITECTURAL DECISION: The Explorer represents a current-state snapshot of the
    codebase, NOT a historical accumulation. When files, pages, endpoints, or tables
    are removed from the codebase, their corresponding explorer entries must be deleted.

    This function is called after each scan to remove entries for paths that were
    not found in the current scan. This ensures the Explorer always reflects the
    actual state of the codebase.

    Args:
        project_id: Project ID for scoping
        entry_type: Entry type ('file', 'page', 'endpoint', 'table', 'task')
        current_paths: Set of paths found in the current scan

    Returns:
        Number of stale entries deleted
    """
    if not current_paths:
        # Safety: if scan returned nothing, don't delete everything
        # This prevents accidental data loss from failed scans
        return 0

    with get_connection() as conn, conn.cursor() as cur:
        # Get all existing paths for this project/type
        cur.execute(
            """
            SELECT path FROM explorer_entries
            WHERE project_id = %s AND entry_type = %s
            """,
            (project_id, entry_type),
        )
        existing_paths = {row[0] for row in cur.fetchall()}

        # Find stale paths (in DB but not in current scan)
        stale_paths = existing_paths - current_paths

        if not stale_paths:
            return 0

        # Delete stale entries
        cur.execute(
            """
            DELETE FROM explorer_entries
            WHERE project_id = %s
              AND entry_type = %s
              AND path = ANY(%s)
            """,
            (project_id, entry_type, list(stale_paths)),
        )
        deleted: int = cur.rowcount or 0
        conn.commit()
        return deleted


def update_health_check(
    entry_id: int,
    health_status: str,
    health_data: dict[str, Any],
) -> bool:
    """Update health check data for an explorer entry.

    Args:
        entry_id: Explorer entry ID
        health_status: New health status ('healthy', 'warning', 'error', 'unknown')
        health_data: Health check results to merge into metadata

    Returns:
        True if updated, False if entry not found
    """
    from psycopg.types.json import Jsonb

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE explorer_entries
            SET health_status = %s,
                metadata = metadata || %s,
                updated_at = NOW()
            WHERE id = %s
            RETURNING id
            """,
            (health_status, Jsonb(health_data), entry_id),
        )
        row = cur.fetchone()
        conn.commit()
        return row is not None


def get_pages_for_health_check(project_id: str) -> list[dict[str, Any]]:
    """Get page entries that need health checks.

    Args:
        project_id: Project ID

    Returns:
        List of page entry dicts with id, path, metadata
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {_ENTRY_COLUMNS}
            FROM explorer_entries
            WHERE project_id = %s
              AND entry_type = 'page'
            ORDER BY path
            """,
            (project_id,),
        )
        rows = cur.fetchall()
        return [_row_to_entry(row) for row in rows]
