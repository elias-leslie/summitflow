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

# Standard column list for explorer_entries queries
_ENTRY_COLUMNS = """id, project_id, entry_type, path, name, health_status,
                   metadata, last_scanned_at, created_at, updated_at"""

# Allowed sort fields for get_entries queries
_ALLOWED_SORT_FIELDS = {"path", "name", "health_status", "last_scanned_at", "created_at"}

# Extensions for code files that can be refactored
REFACTORABLE_EXTENSIONS = {".py", ".ts", ".tsx", ".js", ".mjs"}

# Path patterns to exclude from refactor targets (tests, config, etc.)
REFACTOR_EXCLUDE_PATTERNS = {"test_", "tests/", "__test__", ".test.", ".spec."}


def _to_iso_string(value: datetime | None) -> str | None:
    """Convert datetime to ISO string, returning None if value is None."""
    return value.isoformat() if value else None


def _build_where_clause(
    conditions: list[str],
) -> sql.Composable:
    """Build a WHERE clause from a list of condition strings.

    Joins conditions with AND. If conditions is empty, returns TRUE.

    Args:
        conditions: List of condition strings like ["project_id = %s", "type = %s"]

    Returns:
        sql.Composable ready to format into a query
    """
    if conditions:
        return sql.SQL(" AND ").join(sql.SQL(c) for c in conditions)
    return sql.SQL("TRUE")


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
                    metadata = explorer_entries.metadata || EXCLUDED.metadata,
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
            - association: Filter by association_status ('orphan', 'linked', 'is_component')
            - sort: Sort field (default: 'path')
            - dir: Sort direction ('asc' or 'desc', default: 'asc')
            - limit: Max results (default: 1000)
            - offset: Skip results (default: 0)

    Returns:
        List of entry dicts with association_status field
    """
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

    # Handle association filter in HAVING clause
    association_filter = filters.get("association")
    having_clause = ""
    if association_filter == "is_component":
        having_clause = "HAVING MAX(CASE WHEN c.id IS NOT NULL THEN 1 ELSE 0 END) = 1"
    elif association_filter == "linked":
        having_clause = """HAVING MAX(CASE WHEN c.id IS NOT NULL THEN 1 ELSE 0 END) = 0
                          AND MAX(CASE WHEN ecl.id IS NOT NULL THEN 1 ELSE 0 END) = 1"""
    elif association_filter == "orphan":
        having_clause = """HAVING MAX(CASE WHEN c.id IS NOT NULL THEN 1 ELSE 0 END) = 0
                          AND MAX(CASE WHEN ecl.id IS NOT NULL THEN 1 ELSE 0 END) = 0"""

    where_clause = _build_where_clause(conditions)

    # Sort and pagination
    sort_field = filters.get("sort", "path")
    if sort_field not in _ALLOWED_SORT_FIELDS:
        sort_field = "path"

    sort_dir = "DESC" if filters.get("dir", "asc").lower() == "desc" else "ASC"
    limit = min(int(filters.get("limit", 1000)), 10000)
    offset = int(filters.get("offset", 0))

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            sql.SQL("""
            SELECT ee.id, ee.project_id, ee.entry_type, ee.path, ee.name, ee.health_status,
                   ee.metadata, ee.last_scanned_at, ee.created_at, ee.updated_at,
                   CASE
                       WHEN MAX(CASE WHEN c.id IS NOT NULL THEN 1 ELSE 0 END) = 1 THEN 'is_component'
                       WHEN MAX(CASE WHEN ecl.id IS NOT NULL THEN 1 ELSE 0 END) = 1 THEN 'linked'
                       ELSE 'orphan'
                   END as association_status
            FROM explorer_entries ee
            LEFT JOIN components c ON c.explorer_entry_id = ee.id
            LEFT JOIN explorer_capability_links ecl ON ecl.explorer_entry_id = ee.id
            WHERE {where_clause}
            GROUP BY ee.id, ee.project_id, ee.entry_type, ee.path, ee.name, ee.health_status,
                     ee.metadata, ee.last_scanned_at, ee.created_at, ee.updated_at
            {having_clause}
            ORDER BY {sort_field} {sort_dir}
            LIMIT %s OFFSET %s
            """).format(
                where_clause=where_clause,
                sort_field=sql.Identifier("ee", sort_field),
                sort_dir=sql.SQL(sort_dir),
                having_clause=sql.SQL(having_clause),
            ),
            (*params, limit, offset),
        )
        rows = cur.fetchall()

        return [_row_to_entry_with_association(row) for row in rows]


def _row_to_entry_with_association(row: tuple) -> dict:
    """Convert a database row with association_status to an entry dict."""
    entry = _row_to_entry(row[:10])
    entry["association_status"] = row[10] if len(row) > 10 else "orphan"
    return entry


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

        deleted = cur.rowcount
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
        "last_scanned_at": _to_iso_string(row[7]),
        "created_at": _to_iso_string(row[8]),
        "updated_at": _to_iso_string(row[9]),
    }


# --- Capability Link Functions ---


def create_capability_link(
    project_id: str,
    explorer_entry_id: int,
    capability_id: int,
    link_type: str,
) -> int:
    """Create a link between an explorer entry and a capability.

    Args:
        project_id: Project ID for scoping
        explorer_entry_id: ID of the explorer entry
        capability_id: ID of the capability
        link_type: Type of link (e.g., 'implements', 'exposes', 'required_by')

    Returns:
        ID of the created link
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO explorer_capability_links
                (project_id, explorer_entry_id, capability_id, link_type)
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (project_id, explorer_entry_id, capability_id, link_type),
        )
        result = cur.fetchone()
        conn.commit()
        return result[0] if result else 0


def delete_capability_link(link_id: int) -> bool:
    """Delete a capability link by ID.

    Args:
        link_id: ID of the link to delete

    Returns:
        True if deleted, False if not found
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM explorer_capability_links
            WHERE id = %s
            RETURNING id
            """,
            (link_id,),
        )
        deleted = cur.fetchone() is not None
        conn.commit()
        return deleted


def get_capability_links(capability_id: int) -> list[dict[str, Any]]:
    """Get all explorer entries linked to a capability.

    Args:
        capability_id: ID of the capability

    Returns:
        List of linked explorer entries with link info
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                ecl.id as link_id,
                ecl.link_type,
                ecl.created_at as link_created_at,
                ee.id, ee.project_id, ee.entry_type, ee.path, ee.name,
                ee.health_status, ee.metadata, ee.last_scanned_at,
                ee.created_at, ee.updated_at
            FROM explorer_capability_links ecl
            JOIN explorer_entries ee ON ecl.explorer_entry_id = ee.id
            WHERE ecl.capability_id = %s
            ORDER BY ecl.created_at DESC
            """,
            (capability_id,),
        )
        rows = cur.fetchall()

        return [
            {
                "link_id": row[0],
                "link_type": row[1],
                "link_created_at": _to_iso_string(row[2]),
                "entry": _row_to_entry(row[3:13]),
            }
            for row in rows
        ]


def get_refactor_targets(
    project_id: str,
    priority: str | None = None,
    min_complexity: float | None = None,
    min_lines: int | None = None,
    limit: int = 50,
    code_only: bool = True,
    extensions: list[str] | None = None,
) -> dict[str, Any]:
    """Get files that are candidates for refactoring based on complexity.

    Args:
        project_id: Project ID for scoping
        priority: Filter by refactor_priority ('high', 'medium')
        min_complexity: Minimum complexity_score
        min_lines: Minimum lines_of_code
        limit: Max results (default 50)
        code_only: If True and extensions is None, filter to REFACTORABLE_EXTENSIONS
        extensions: Explicit list of extensions to include (overrides code_only)

    Returns:
        Dict with targets list and summary stats
    """
    conditions = [
        "project_id = %s",
        "entry_type = 'file'",
        "(metadata->>'refactor_priority') IS NOT NULL",
        "(metadata->>'refactor_priority') != 'none'",
    ]
    params: list[Any] = [project_id]

    # Filter by extensions
    if extensions:
        conditions.append("(metadata->>'extension') = ANY(%s)")
        params.append(extensions)
    elif code_only:
        conditions.append("(metadata->>'extension') = ANY(%s)")
        params.append(list(REFACTORABLE_EXTENSIONS))

    # Exclude test files and other non-production code
    for pattern in REFACTOR_EXCLUDE_PATTERNS:
        conditions.append("path NOT LIKE %s")
        params.append(f"%{pattern}%")

    if priority:
        conditions.append("(metadata->>'refactor_priority') = %s")
        params.append(priority)

    if min_complexity:
        conditions.append("(metadata->>'complexity_score')::float >= %s")
        params.append(min_complexity)

    if min_lines:
        conditions.append("(metadata->>'lines_of_code')::int >= %s")
        params.append(min_lines)

    with get_connection() as conn, conn.cursor() as cur:
        where_clause_sql = sql.SQL(" AND ").join(sql.SQL(c) for c in conditions)

        cur.execute(
            sql.SQL("""
            SELECT path, name,
                   (metadata->>'complexity_score')::float as complexity_score,
                   (metadata->>'lines_of_code')::int as lines_of_code,
                   (metadata->>'function_count')::int as function_count,
                   (metadata->>'class_count')::int as class_count,
                   (metadata->>'refactor_priority') as priority,
                   CASE
                       WHEN (metadata->>'complexity_score')::float > 15 THEN 'High complexity score'
                       WHEN (metadata->>'lines_of_code')::int > 500 THEN 'High line count'
                       WHEN (metadata->>'complexity_score')::float > 10 THEN 'Medium complexity'
                       ELSE 'Medium line count'
                   END as reason,
                   COALESCE((metadata->>'commit_count_90d')::int, 0) as commit_count_90d,
                   COALESCE((metadata->>'test_file_exists')::boolean, false) as test_file_exists,
                   -- Hotspot score: high churn + high complexity = high priority
                   ROUND((COALESCE((metadata->>'commit_count_90d')::int, 0) *
                         COALESCE((metadata->>'complexity_score')::float, 0))::numeric, 2) as hotspot_score
            FROM explorer_entries
            WHERE {where_clause}
            ORDER BY
                CASE WHEN (metadata->>'refactor_priority') = 'high' THEN 0 ELSE 1 END,
                -- Sort by hotspot_score DESC, then complexity
                COALESCE((metadata->>'commit_count_90d')::int, 0) *
                COALESCE((metadata->>'complexity_score')::float, 0) DESC,
                (metadata->>'complexity_score')::float DESC
            LIMIT %s
            """).format(where_clause=where_clause_sql),
            (*params, limit),
        )
        rows = cur.fetchall()

        targets = [
            {
                "path": row[0],
                "name": row[1],
                "complexity_score": row[2],
                "lines_of_code": row[3],
                "function_count": row[4],
                "class_count": row[5],
                "priority": row[6],
                "reason": row[7],
                "commit_count_90d": row[8],
                "test_file_exists": row[9],
                "hotspot_score": row[10],
            }
            for row in rows
        ]

        # Get summary counts (same extension filter as main query)
        summary_conditions = [
            "project_id = %s",
            "entry_type = 'file'",
            "(metadata->>'refactor_priority') IS NOT NULL",
            "(metadata->>'refactor_priority') != 'none'",
        ]
        summary_params: list[Any] = [project_id]

        if extensions:
            summary_conditions.append("(metadata->>'extension') = ANY(%s)")
            summary_params.append(extensions)
        elif code_only:
            summary_conditions.append("(metadata->>'extension') = ANY(%s)")
            summary_params.append(list(REFACTORABLE_EXTENSIONS))

        # Exclude test files (same as main query)
        for pattern in REFACTOR_EXCLUDE_PATTERNS:
            summary_conditions.append("path NOT LIKE %s")
            summary_params.append(f"%{pattern}%")

        summary_where = sql.SQL(" AND ").join(sql.SQL(c) for c in summary_conditions)
        cur.execute(
            sql.SQL("""
            SELECT
                (metadata->>'refactor_priority') as priority,
                COUNT(*) as count,
                SUM((metadata->>'complexity_score')::float) as total_complexity
            FROM explorer_entries
            WHERE {where_clause}
            GROUP BY (metadata->>'refactor_priority')
            """).format(where_clause=summary_where),
            summary_params,
        )
        summary_rows = cur.fetchall()
        summary = {
            "high_priority_count": 0,
            "medium_priority_count": 0,
            "total_complexity": 0.0,
        }
        for row in summary_rows:
            if row[0] == "high":
                summary["high_priority_count"] = row[1]
            elif row[0] == "medium":
                summary["medium_priority_count"] = row[1]
            summary["total_complexity"] += row[2] or 0

        return {"targets": targets, "summary": summary}


def count_stale_metadata_entries(project_id: str, min_version: int = 2) -> int:
    """Count entries with outdated or missing schema version.

    Args:
        project_id: Project ID for scoping
        min_version: Minimum schema version to be considered current

    Returns:
        Count of entries with stale metadata
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*)
            FROM explorer_entries
            WHERE project_id = %s
              AND entry_type = 'file'
              AND (
                  (metadata->>'_schema_version') IS NULL
                  OR (metadata->>'_schema_version')::int < %s
              )
            """,
            (project_id, min_version),
        )
        row = cur.fetchone()
        return row[0] if row else 0


def _get_unlinked_entries(
    cur: Any, project_id: str, entry_type: str, check_components: bool = True
) -> list[tuple[Any, ...]]:
    """Get entries not linked to any capability.

    Args:
        cur: Database cursor
        project_id: Project ID for scoping
        entry_type: Entry type to query
        check_components: If True, also exclude entries linked via components table

    Returns:
        List of tuples (path, name, metadata)
    """
    if check_components:
        cur.execute(
            """
            SELECT ee.path, ee.name, ee.metadata
            FROM explorer_entries ee
            LEFT JOIN explorer_capability_links ecl ON ecl.explorer_entry_id = ee.id
            LEFT JOIN components c ON c.explorer_entry_id = ee.id
            WHERE ee.project_id = %s
              AND ee.entry_type = %s
              AND ecl.id IS NULL
              AND c.id IS NULL
            ORDER BY ee.path
            """,
            (project_id, entry_type),
        )
    else:
        cur.execute(
            """
            SELECT ee.path, ee.name, ee.metadata
            FROM explorer_entries ee
            LEFT JOIN explorer_capability_links ecl ON ecl.explorer_entry_id = ee.id
            WHERE ee.project_id = %s
              AND ee.entry_type = %s
              AND ecl.id IS NULL
            ORDER BY ee.path
            """,
            (project_id, entry_type),
        )
    return cur.fetchall()


def get_coverage_gaps(project_id: str) -> dict[str, Any]:
    """Get endpoints, pages, and tables without capability links.

    Args:
        project_id: Project ID for scoping

    Returns:
        Dict with uncovered_endpoints, uncovered_pages, orphan_tables arrays
    """
    with get_connection() as conn, conn.cursor() as cur:
        endpoint_rows = _get_unlinked_entries(cur, project_id, "endpoint")
        uncovered_endpoints = [
            {"path": row[0], "name": row[1], "method": (row[2] or {}).get("method", "")}
            for row in endpoint_rows
        ]

        page_rows = _get_unlinked_entries(cur, project_id, "page")
        uncovered_pages = [
            {"path": row[0], "name": row[1], "route": (row[2] or {}).get("route", "")}
            for row in page_rows
        ]

        table_rows = _get_unlinked_entries(cur, project_id, "table", check_components=False)
        orphan_tables = [
            {
                "path": row[0],
                "name": row[1],
                "column_count": len((row[2] or {}).get("columns", [])),
            }
            for row in table_rows
        ]

        return {
            "uncovered_endpoints": uncovered_endpoints,
            "uncovered_pages": uncovered_pages,
            "orphan_tables": orphan_tables,
            "summary": {
                "total_uncovered": len(uncovered_endpoints)
                + len(uncovered_pages)
                + len(orphan_tables),
                "endpoint_count": len(uncovered_endpoints),
                "page_count": len(uncovered_pages),
                "table_count": len(orphan_tables),
            },
        }


def get_multi_capability_files(
    project_id: str,
    min_capabilities: int = 3,
    limit: int = 50,
) -> dict[str, Any]:
    """Get files linked to multiple capabilities (potential god files).

    Args:
        project_id: Project ID for scoping
        min_capabilities: Minimum number of capabilities (default 3)
        limit: Max results (default 50)

    Returns:
        Dict with files list and summary stats
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                ee.path,
                ee.name,
                (ee.metadata->>'lines_of_code')::int as lines_of_code,
                (ee.metadata->>'complexity_score')::float as complexity_score,
                COUNT(DISTINCT ecl.capability_id) as capability_count,
                ARRAY_AGG(DISTINCT c.name) as capability_names
            FROM explorer_entries ee
            JOIN explorer_capability_links ecl ON ecl.explorer_entry_id = ee.id
            JOIN capabilities c ON c.id = ecl.capability_id
            WHERE ee.project_id = %s
              AND ee.entry_type = 'file'
            GROUP BY ee.id, ee.path, ee.name, ee.metadata
            HAVING COUNT(DISTINCT ecl.capability_id) >= %s
            ORDER BY COUNT(DISTINCT ecl.capability_id) DESC, ee.path
            LIMIT %s
            """,
            (project_id, min_capabilities, limit),
        )
        rows = cur.fetchall()

        files = []
        for row in rows:
            cap_count = row[4]
            recommendation = (
                "Critical: Consider splitting this file"
                if cap_count >= 5
                else "Consider reviewing responsibilities"
            )
            files.append(
                {
                    "path": row[0],
                    "name": row[1],
                    "lines_of_code": row[2],
                    "complexity_score": row[3],
                    "capability_count": cap_count,
                    "capabilities": row[5] if row[5] else [],
                    "recommendation": recommendation,
                }
            )

        return {
            "files": files,
            "summary": {
                "total_files": len(files),
                "max_capabilities": files[0]["capability_count"] if files else 0,
            },
        }


def get_entry_capabilities(explorer_entry_id: int) -> list[dict[str, Any]]:
    """Get all capabilities linked to an explorer entry.

    Args:
        explorer_entry_id: ID of the explorer entry

    Returns:
        List of linked capabilities with link info
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                ecl.id as link_id,
                ecl.link_type,
                ecl.created_at as link_created_at,
                c.id, c.project_id, c.component_id, c.capability_id, c.name,
                c.description, c.status, c.verification_url, c.priority,
                c.created_at, c.updated_at
            FROM explorer_capability_links ecl
            JOIN capabilities c ON ecl.capability_id = c.id
            WHERE ecl.explorer_entry_id = %s
            ORDER BY ecl.created_at DESC
            """,
            (explorer_entry_id,),
        )
        rows = cur.fetchall()

        return [
            {
                "link_id": row[0],
                "link_type": row[1],
                "link_created_at": _to_iso_string(row[2]),
                "capability": {
                    "id": row[3],
                    "project_id": row[4],
                    "component_id": row[5],
                    "capability_id": row[6],
                    "name": row[7],
                    "description": row[8],
                    "status": row[9],
                    "verification_url": row[10],
                    "priority": row[11],
                    "created_at": _to_iso_string(row[12]),
                    "updated_at": _to_iso_string(row[13]),
                },
            }
            for row in rows
        ]


# --- Scan State Functions ---


def get_scan_state(project_id: str) -> dict[str, Any] | None:
    """Get the current scan state for a project.

    Args:
        project_id: Project ID for scoping

    Returns:
        Scan state dict or None if no scan has been run
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT project_id, status, current_type, types_total, types_completed,
                   started_at, completed_at, error, results, updated_at
            FROM scan_states
            WHERE project_id = %s
            """,
            (project_id,),
        )
        row = cur.fetchone()

        if not row:
            return None

        return {
            "project_id": row[0],
            "status": row[1],
            "current_type": row[2],
            "types_total": row[3],
            "types_completed": row[4],
            "started_at": _to_iso_string(row[5]),
            "completed_at": _to_iso_string(row[6]),
            "error": row[7],
            "results": row[8] if row[8] else {},
            "updated_at": _to_iso_string(row[9]),
        }


def update_scan_state(
    project_id: str,
    status: str,
    current_type: str | None = None,
    types_total: int = 0,
    types_completed: int = 0,
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
    error: str | None = None,
    results: dict | None = None,
) -> dict[str, Any]:
    """Update (or create) the scan state for a project.

    Args:
        project_id: Project ID for scoping
        status: Scan status ('idle', 'running', 'completed', 'failed')
        current_type: Currently scanning type
        types_total: Total number of types to scan
        types_completed: Number of types completed
        started_at: When the scan started
        completed_at: When the scan completed
        error: Error message if failed
        results: Scan results (counts per type)

    Returns:
        Updated scan state dict
    """
    now = datetime.now(UTC)

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO scan_states (
                project_id, status, current_type, types_total, types_completed,
                started_at, completed_at, error, results, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (project_id)
            DO UPDATE SET
                status = EXCLUDED.status,
                current_type = EXCLUDED.current_type,
                types_total = EXCLUDED.types_total,
                types_completed = EXCLUDED.types_completed,
                started_at = EXCLUDED.started_at,
                completed_at = EXCLUDED.completed_at,
                error = EXCLUDED.error,
                results = EXCLUDED.results,
                updated_at = EXCLUDED.updated_at
            RETURNING project_id, status, current_type, types_total, types_completed,
                      started_at, completed_at, error, results, updated_at
            """,
            (
                project_id,
                status,
                current_type,
                types_total,
                types_completed,
                started_at,
                completed_at,
                error,
                json.dumps(results or {}),
                now,
            ),
        )
        row = cur.fetchone()
        conn.commit()

        if not row:
            # Should never happen with RETURNING, but satisfy type checker
            return {
                "project_id": project_id,
                "status": status,
                "current_type": current_type,
                "types_total": types_total,
                "types_completed": types_completed,
                "started_at": _to_iso_string(started_at),
                "completed_at": _to_iso_string(completed_at),
                "error": error,
                "results": results or {},
                "updated_at": _to_iso_string(now),
            }

        return {
            "project_id": row[0],
            "status": row[1],
            "current_type": row[2],
            "types_total": row[3],
            "types_completed": row[4],
            "started_at": _to_iso_string(row[5]),
            "completed_at": _to_iso_string(row[6]),
            "error": row[7],
            "results": row[8] if row[8] else {},
            "updated_at": _to_iso_string(row[9]),
        }
