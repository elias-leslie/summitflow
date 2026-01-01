"""Explorer analysis storage - Analysis and refactoring target queries.

This module handles:
- Refactor target identification
- Coverage gap analysis
- Multi-capability file detection (god files)
- Stale metadata detection
"""

from __future__ import annotations

from typing import Any

from psycopg import sql

from .connection import get_connection

# Extensions for code files that can be refactored
REFACTORABLE_EXTENSIONS = {".py", ".ts", ".tsx", ".js", ".mjs"}

# Path patterns to exclude from refactor targets (tests, config, etc.)
REFACTOR_EXCLUDE_PATTERNS = {"test_", "tests/", "__test__", ".test.", ".spec."}


def _build_refactor_filter_conditions(
    project_id: str,
    extensions: list[str] | None = None,
    code_only: bool = True,
) -> tuple[list[str], list[Any]]:
    """Build WHERE conditions for refactor target queries.

    Args:
        project_id: Project ID for scoping
        extensions: Explicit list of extensions to include
        code_only: If True and extensions is None, filter to REFACTORABLE_EXTENSIONS

    Returns:
        Tuple of (conditions list, params list)
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

    return conditions, params


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
    return list(cur.fetchall())


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
    # Build base filter conditions
    conditions, params = _build_refactor_filter_conditions(
        project_id=project_id,
        extensions=extensions,
        code_only=code_only,
    )

    # Add optional filters for main query
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

        # Get summary counts using same base filter
        summary_conditions, summary_params = _build_refactor_filter_conditions(
            project_id=project_id,
            extensions=extensions,
            code_only=code_only,
        )
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
    """Count file entries with outdated or missing schema version.

    Excludes directories since they don't have the same metadata fields.

    Args:
        project_id: Project ID for scoping
        min_version: Minimum schema version to be considered current

    Returns:
        Count of file entries with stale metadata
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*)
            FROM explorer_entries
            WHERE project_id = %s
              AND entry_type = 'file'
              AND COALESCE((metadata->>'is_directory')::boolean, false) = false
              AND (
                  (metadata->>'_schema_version') IS NULL
                  OR (metadata->>'_schema_version')::int < %s
              )
            """,
            (project_id, min_version),
        )
        row = cur.fetchone()
        return row[0] if row else 0


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
