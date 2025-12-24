"""Explorer storage layer - ALL database operations for explorer.

This module handles:
- CRUD operations for explorer_entries
- Querying with filters, pagination, sorting
- Statistics aggregation
- Relationship management (explorer_relationships)

Per architecture: No other module should contain direct explorer DB queries.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from psycopg import sql

from .connection import get_connection


def upsert_entries(project_id: str, entry_type: str, entries: list[dict]) -> int:
    """Upsert explorer entries (insert or update on conflict).

    Args:
        project_id: Project ID for scoping
        entry_type: Entry type ('file', 'table', 'task', 'endpoint')
        entries: List of entry dicts with keys: path, name, health_status, metadata

    Returns:
        Number of entries upserted
    """
    if not entries:
        return 0

    now = datetime.now(UTC)

    with get_connection() as conn, conn.cursor() as cur:
        count = 0
        for entry in entries:
            cur.execute(
                """
                INSERT INTO explorer_entries (
                    project_id, entry_type, path, name, health_status,
                    metadata, last_scanned_at, created_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (project_id, entry_type, path)
                DO UPDATE SET
                    name = EXCLUDED.name,
                    health_status = EXCLUDED.health_status,
                    metadata = EXCLUDED.metadata,
                    last_scanned_at = EXCLUDED.last_scanned_at,
                    updated_at = EXCLUDED.updated_at
                """,
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
            count += 1

        conn.commit()
        return count


def get_entries(project_id: str, filters: dict | None = None) -> list[dict]:
    """Get explorer entries with optional filters.

    Args:
        project_id: Project ID for scoping
        filters: Optional dict with keys:
            - type: Filter by entry_type
            - health: Filter by health_status
            - path: Filter by path prefix (LIKE 'path%')
            - sort: Sort field (default: 'path')
            - dir: Sort direction ('asc' or 'desc', default: 'asc')
            - limit: Max results (default: 1000)
            - offset: Skip results (default: 0)

    Returns:
        List of entry dicts
    """
    filters = filters or {}

    # Build WHERE clause
    conditions = ["project_id = %s"]
    params: list[Any] = [project_id]

    if filters.get("type"):
        conditions.append("entry_type = %s")
        params.append(filters["type"])

    if filters.get("health"):
        conditions.append("health_status = %s")
        params.append(filters["health"])

    if filters.get("path"):
        conditions.append("path LIKE %s")
        params.append(f"{filters['path']}%")

    # Build WHERE clause from conditions
    if conditions:
        where_clause = sql.SQL(" AND ").join(sql.SQL(c) for c in conditions)  # type: ignore[arg-type]
    else:
        where_clause = sql.SQL("TRUE")

    # Sort and pagination
    sort_field = filters.get("sort", "path")
    # Whitelist allowed sort fields to prevent SQL injection
    allowed_sorts = {"path", "name", "health_status", "last_scanned_at", "created_at"}
    if sort_field not in allowed_sorts:
        sort_field = "path"

    sort_dir = "DESC" if filters.get("dir", "asc").lower() == "desc" else "ASC"
    limit = min(int(filters.get("limit", 1000)), 10000)
    offset = int(filters.get("offset", 0))

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            sql.SQL("""
            SELECT id, project_id, entry_type, path, name, health_status,
                   metadata, last_scanned_at, created_at, updated_at
            FROM explorer_entries
            WHERE {where_clause}
            ORDER BY {sort_field} {sort_dir}
            LIMIT %s OFFSET %s
            """).format(
                where_clause=where_clause,
                sort_field=sql.Identifier(sort_field),
                sort_dir=sql.SQL(sort_dir),
            ),
            (*params, limit, offset),
        )
        rows = cur.fetchall()

        return [_row_to_entry(row) for row in rows]


def get_entry(project_id: str, entry_type: str, path: str) -> dict | None:
    """Get a single explorer entry by type and path.

    Args:
        project_id: Project ID for scoping
        entry_type: Entry type
        path: Entry path

    Returns:
        Entry dict or None if not found
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, project_id, entry_type, path, name, health_status,
                   metadata, last_scanned_at, created_at, updated_at
            FROM explorer_entries
            WHERE project_id = %s AND entry_type = %s AND path = %s
            """,
            (project_id, entry_type, path),
        )
        row = cur.fetchone()

        if not row:
            return None

        return _row_to_entry(row)


def get_children(project_id: str, entry_type: str, parent_path: str) -> list[dict]:
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
                """
                SELECT id, project_id, entry_type, path, name, health_status,
                       metadata, last_scanned_at, created_at, updated_at
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
                """
                SELECT id, project_id, entry_type, path, name, health_status,
                       metadata, last_scanned_at, created_at, updated_at
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


def get_stats(project_id: str, entry_type: str | None = None) -> dict:
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
    with get_connection() as conn, conn.cursor() as cur:
        # Build WHERE clause
        where_clause = "WHERE project_id = %s"
        params: list[Any] = [project_id]
        if entry_type:
            where_clause += " AND entry_type = %s"
            params.append(entry_type)

        # Count by type
        cur.execute(
            f"""
            SELECT entry_type, COUNT(*) as count
            FROM explorer_entries
            {where_clause}
            GROUP BY entry_type
            """,
            params,
        )
        by_type = {row[0]: row[1] for row in cur.fetchall()}

        # Count by health
        cur.execute(
            f"""
            SELECT health_status, COUNT(*) as count
            FROM explorer_entries
            {where_clause}
            GROUP BY health_status
            """,
            params,
        )
        by_health = {row[0]: row[1] for row in cur.fetchall()}

        # Total and last scanned
        cur.execute(
            f"""
            SELECT COUNT(*), MAX(last_scanned_at)
            FROM explorer_entries
            {where_clause}
            """,
            params,
        )
        row = cur.fetchone()
        total = row[0] if row else 0
        last_scanned = row[1].isoformat() if row and row[1] else None

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

        deleted = cur.rowcount
        conn.commit()
        return deleted


def upsert_relationships(project_id: str, relationships: list[dict]) -> int:
    """Upsert explorer relationships.

    Args:
        project_id: Project ID for scoping
        relationships: List of relationship dicts with keys:
            source_type, source_path, target_type, target_path, relationship

    Returns:
        Number of relationships upserted
    """
    if not relationships:
        return 0

    now = datetime.now(UTC)

    with get_connection() as conn, conn.cursor() as cur:
        count = 0
        for rel in relationships:
            cur.execute(
                """
                INSERT INTO explorer_relationships (
                    project_id, source_type, source_path,
                    target_type, target_path, relationship, created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (project_id, source_type, source_path, target_type, target_path, relationship)
                DO NOTHING
                """,
                (
                    project_id,
                    rel.get("source_type"),
                    rel.get("source_path"),
                    rel.get("target_type"),
                    rel.get("target_path"),
                    rel.get("relationship"),
                    now,
                ),
            )
            count += 1

        conn.commit()
        return count


def get_relationships(
    project_id: str,
    source_type: str | None = None,
    source_path: str | None = None,
    target_type: str | None = None,
    target_path: str | None = None,
) -> list[dict]:
    """Get explorer relationships with optional filters.

    Args:
        project_id: Project ID for scoping
        source_type: Optional filter by source type
        source_path: Optional filter by source path
        target_type: Optional filter by target type
        target_path: Optional filter by target path

    Returns:
        List of relationship dicts
    """
    conditions = ["project_id = %s"]
    params: list[Any] = [project_id]

    if source_type:
        conditions.append("source_type = %s")
        params.append(source_type)
    if source_path:
        conditions.append("source_path = %s")
        params.append(source_path)
    if target_type:
        conditions.append("target_type = %s")
        params.append(target_type)
    if target_path:
        conditions.append("target_path = %s")
        params.append(target_path)

    if conditions:
        where_clause = sql.SQL(" AND ").join(sql.SQL(c) for c in conditions)  # type: ignore[arg-type]
    else:
        where_clause = sql.SQL("TRUE")

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            sql.SQL("""
            SELECT id, project_id, source_type, source_path,
                   target_type, target_path, relationship, created_at
            FROM explorer_relationships
            WHERE {where_clause}
            ORDER BY created_at DESC
            """).format(where_clause=where_clause),
            params,
        )
        rows = cur.fetchall()

        return [
            {
                "id": row[0],
                "project_id": row[1],
                "source_type": row[2],
                "source_path": row[3],
                "target_type": row[4],
                "target_path": row[5],
                "relationship": row[6],
                "created_at": row[7].isoformat() if row[7] else None,
            }
            for row in rows
        ]


def delete_relationships(
    project_id: str,
    source_type: str | None = None,
    source_path: str | None = None,
) -> int:
    """Delete explorer relationships.

    Args:
        project_id: Project ID for scoping
        source_type: Optional filter by source type
        source_path: Optional filter by source path (requires source_type)

    Returns:
        Number of relationships deleted
    """
    with get_connection() as conn, conn.cursor() as cur:
        if source_type and source_path:
            cur.execute(
                """
                DELETE FROM explorer_relationships
                WHERE project_id = %s AND source_type = %s AND source_path = %s
                """,
                (project_id, source_type, source_path),
            )
        elif source_type:
            cur.execute(
                """
                DELETE FROM explorer_relationships
                WHERE project_id = %s AND source_type = %s
                """,
                (project_id, source_type),
            )
        else:
            cur.execute(
                """
                DELETE FROM explorer_relationships
                WHERE project_id = %s
                """,
                (project_id,),
            )

        deleted = cur.rowcount
        conn.commit()
        return deleted


def _row_to_entry(row: tuple) -> dict:
    """Convert a database row to an entry dict."""
    return {
        "id": row[0],
        "project_id": row[1],
        "entry_type": row[2],
        "path": row[3],
        "name": row[4],
        "health_status": row[5],
        "metadata": row[6] if row[6] else {},
        "last_scanned_at": row[7].isoformat() if row[7] else None,
        "created_at": row[8].isoformat() if row[8] else None,
        "updated_at": row[9].isoformat() if row[9] else None,
    }
