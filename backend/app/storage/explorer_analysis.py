"""Explorer analysis storage - Analysis and refactoring target queries.

This module handles:
- Refactor target identification
- Coverage gap analysis (list endpoints/pages/tables)
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


def _get_unlinked_entries(cur: Any, project_id: str, entry_type: str) -> list[tuple[Any, ...]]:
    """Get entries of a given type.

    Args:
        cur: Database cursor
        project_id: Project ID for scoping
        entry_type: Entry type to query

    Returns:
        List of tuples (path, name, metadata)
    """
    cur.execute(
        """
        SELECT ee.path, ee.name, ee.metadata
        FROM explorer_entries ee
        WHERE ee.project_id = %s
          AND ee.entry_type = %s
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
                       WHEN metadata->'health_flags' IS NOT NULL
                            AND jsonb_typeof(metadata->'health_flags') = 'object'
                            AND (SELECT count(*) FROM jsonb_object_keys(metadata->'health_flags')) >= 3
                            THEN 'Multiple structural issues'
                       WHEN (metadata->>'complexity_score')::float > 10 THEN 'Medium complexity'
                       WHEN (metadata->>'lines_of_code')::int > 300 THEN 'Medium line count'
                       WHEN (metadata->>'bloat_level') = 'warning' THEN 'File bloat'
                       ELSE 'Structural issues'
                   END as reason,
                   COALESCE((metadata->>'commit_count_90d')::int, 0) as commit_count_90d,
                   COALESCE((metadata->>'test_file_exists')::boolean, false) as test_file_exists,
                   -- Hotspot score: high churn + high complexity = high priority
                   ROUND((COALESCE((metadata->>'commit_count_90d')::int, 0) *
                         COALESCE((metadata->>'complexity_score')::float, 0))::numeric, 2) as hotspot_score,
                   COALESCE(metadata->>'complexity_method', 'heuristic') as complexity_method,
                   COALESCE(metadata->'health_flags', '[]'::jsonb) as health_flags,
                   COALESCE(metadata->'refactor_issues', '[]'::jsonb) as refactor_issues
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
                "hotspot_score": float(row[10]) if row[10] is not None else 0.0,
                "complexity_method": row[11],
                "health_flags": list(row[12].keys()) if isinstance(row[12], dict) else row[12] if isinstance(row[12], list) else [],
                "refactor_issues": row[13] if isinstance(row[13], list) else [],
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
    """Get all endpoints, pages, and tables for coverage analysis.

    Args:
        project_id: Project ID for scoping

    Returns:
        Dict with endpoints, pages, tables arrays
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

        table_rows = _get_unlinked_entries(cur, project_id, "table")
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
