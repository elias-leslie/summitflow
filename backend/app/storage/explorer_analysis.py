"""Explorer analysis storage - Analysis and refactoring target queries.

This module handles:
- Refactor target identification
- Coverage gap analysis (list endpoints/pages/tables)
- Stale metadata detection
"""

from __future__ import annotations

from typing import Any

from psycopg import sql

from app.services.refactor_promotion import assess_refactor_target

from .connection import get_cursor
from .explorer_analysis_helpers import (
    REFACTOR_SUMMARY_SQL,
    REFACTOR_TARGETS_SQL,
    STALE_METADATA_SQL,
    UNLINKED_ENTRIES_SQL,
    build_summary,
    row_to_target,
)
from .explorer_symbols import summarize_symbols_for_file

# Extensions for code files that can be refactored
REFACTORABLE_EXTENSIONS = {".py", ".ts", ".tsx", ".js", ".mjs"}

# Path patterns to exclude from refactor targets (tests, config, etc.)
REFACTOR_EXCLUDE_PATTERNS = {"test_", "tests/", "__test__", ".test.", ".spec."}


def _build_where(conditions: list[str]) -> sql.Composable:
    return sql.SQL(" AND ").join(sql.SQL(c) for c in conditions)


def _build_refactor_filter_conditions(
    project_id: str,
    extensions: list[str] | None = None,
    code_only: bool = True,
) -> tuple[list[str], list[Any]]:
    """Build WHERE conditions for refactor target queries."""
    conditions = [
        "project_id = %s",
        "entry_type = 'file'",
        "(metadata->>'refactor_priority') IS NOT NULL",
        "(metadata->>'refactor_priority') != 'none'",
    ]
    params: list[Any] = [project_id]

    ext_list = extensions or (list(REFACTORABLE_EXTENSIONS) if code_only else None)
    if ext_list:
        conditions.append("(metadata->>'extension') = ANY(%s)")
        params.append(ext_list)

    for pattern in REFACTOR_EXCLUDE_PATTERNS:
        conditions.append("path NOT LIKE %s")
        params.append(f"%{pattern}%")

    return conditions, params


def _add_optional_filters(
    conditions: list[str],
    params: list[Any],
    priority: str | None,
    min_complexity: float | None,
    min_lines: int | None,
) -> None:
    """Append optional WHERE conditions and params in place."""
    if priority:
        conditions.append("(metadata->>'refactor_priority') = %s")
        params.append(priority)
    if min_complexity:
        conditions.append("(metadata->>'complexity_score')::float >= %s")
        params.append(min_complexity)
    if min_lines:
        conditions.append("(metadata->>'lines_of_code')::int >= %s")
        params.append(min_lines)


def _get_unlinked_entries(cur: Any, project_id: str, entry_type: str) -> list[tuple[Any, ...]]:
    """Get entries of a given type, returning (path, name, metadata) tuples."""
    cur.execute(UNLINKED_ENTRIES_SQL, (project_id, entry_type))
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
    conditions, params = _build_refactor_filter_conditions(
        project_id=project_id, extensions=extensions, code_only=code_only
    )
    _add_optional_filters(conditions, params, priority, min_complexity, min_lines)

    summary_conditions, summary_params = _build_refactor_filter_conditions(
        project_id=project_id, extensions=extensions, code_only=code_only
    )

    with get_cursor() as cur:
        cur.execute(
            sql.SQL(REFACTOR_TARGETS_SQL).format(where_clause=_build_where(conditions)),
            (*params, limit),
        )
        targets = [row_to_target(row) for row in cur.fetchall()]

        cur.execute(
            sql.SQL(REFACTOR_SUMMARY_SQL).format(where_clause=_build_where(summary_conditions)),
            summary_params,
        )
        summary = build_summary(cur.fetchall())

    for target in targets:
        target["top_symbols"] = summarize_symbols_for_file(project_id, target["path"])
        target.update(assess_refactor_target(target).to_dict())

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
    with get_cursor() as cur:
        cur.execute(STALE_METADATA_SQL, (project_id, min_version))
        row = cur.fetchone()
        return row[0] if row else 0


def get_coverage_gaps(project_id: str) -> dict[str, Any]:
    """Get all endpoints, pages, and tables for coverage analysis.

    Args:
        project_id: Project ID for scoping

    Returns:
        Dict with endpoints, pages, tables arrays
    """
    with get_cursor() as cur:
        endpoint_rows = _get_unlinked_entries(cur, project_id, "endpoint")
        uncovered_endpoints = [
            {"path": r[0], "name": r[1], "method": (r[2] or {}).get("method", "")}
            for r in endpoint_rows
        ]

        page_rows = _get_unlinked_entries(cur, project_id, "page")
        uncovered_pages = [
            {"path": r[0], "name": r[1], "route": (r[2] or {}).get("route", "")}
            for r in page_rows
        ]

        table_rows = _get_unlinked_entries(cur, project_id, "table")
        orphan_tables = [
            {"path": r[0], "name": r[1], "column_count": len((r[2] or {}).get("columns", []))}
            for r in table_rows
        ]

        return {
            "uncovered_endpoints": uncovered_endpoints,
            "uncovered_pages": uncovered_pages,
            "orphan_tables": orphan_tables,
            "summary": {
                "total_uncovered": len(uncovered_endpoints) + len(uncovered_pages) + len(orphan_tables),
                "endpoint_count": len(uncovered_endpoints),
                "page_count": len(uncovered_pages),
                "table_count": len(orphan_tables),
            },
        }
