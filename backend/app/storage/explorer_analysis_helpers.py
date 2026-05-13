"""Helper constants and functions for explorer_analysis.py.

Extracted SQL templates and row-processing helpers to keep the main
module under 200 lines.
"""

from __future__ import annotations

from typing import Any

# -- SQL templates ----------------------------------------------------------

REFACTOR_TARGETS_SQL = """
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
           WHEN metadata->'health_flags' ? 'has_long_functions' THEN 'Long functions'
           WHEN metadata->'health_flags' ? 'deep_nesting' THEN 'Deep nesting'
           WHEN metadata->'health_flags' ? 'has_large_classes' THEN 'Large classes'
           WHEN metadata->'health_flags' ? 'too_many_functions' THEN 'Too many functions'
           WHEN (metadata->>'lines_of_code')::int > 300 THEN 'Medium line count'
           WHEN (metadata->>'bloat_level') = 'warning' THEN 'File bloat'
           ELSE 'Structural issues'
       END as reason,
       COALESCE((metadata->>'commit_count_90d')::int, 0) as commit_count_90d,
       COALESCE((metadata->>'test_file_exists')::boolean, false) as test_file_exists,
       ROUND((COALESCE((metadata->>'commit_count_90d')::int, 0) *
             COALESCE((metadata->>'complexity_score')::float, 0))::numeric, 2) as hotspot_score,
       COALESCE(metadata->>'complexity_method', 'heuristic') as complexity_method,
       COALESCE(metadata->'health_flags', '[]'::jsonb) as health_flags,
       COALESCE(metadata->'refactor_issues', '[]'::jsonb) as refactor_issues
FROM explorer_entries
WHERE {where_clause}
ORDER BY
    CASE WHEN (metadata->>'refactor_priority') = 'high' THEN 0 ELSE 1 END,
    COALESCE((metadata->>'commit_count_90d')::int, 0) *
    COALESCE((metadata->>'complexity_score')::float, 0) DESC,
    (metadata->>'complexity_score')::float DESC
LIMIT %s
"""

REFACTOR_SUMMARY_SQL = """
SELECT
    (metadata->>'refactor_priority') as priority,
    COUNT(*) as count,
    SUM((metadata->>'complexity_score')::float) as total_complexity
FROM explorer_entries
WHERE {where_clause}
GROUP BY (metadata->>'refactor_priority')
"""

STALE_METADATA_SQL = """
SELECT COUNT(*)
FROM explorer_entries
WHERE project_id = %s
  AND entry_type = 'file'
  AND COALESCE((metadata->>'is_directory')::boolean, false) = false
  AND (
      (metadata->>'_schema_version') IS NULL
      OR (metadata->>'_schema_version')::int < %s
  )
"""

UNLINKED_ENTRIES_SQL = """
SELECT ee.path, ee.name, ee.metadata
FROM explorer_entries ee
WHERE ee.project_id = %s
  AND ee.entry_type = %s
ORDER BY ee.path
"""

# -- Row processors ---------------------------------------------------------


def row_to_target(row: tuple[Any, ...]) -> dict[str, Any]:
    """Convert a database row to a refactor target dict."""
    health_flags_raw = row[12]
    if isinstance(health_flags_raw, dict):
        health_flags: list[Any] = list(health_flags_raw.keys())
    elif isinstance(health_flags_raw, list):
        health_flags = health_flags_raw
    else:
        health_flags = []

    return {
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
        "health_flags": health_flags,
        "refactor_issues": row[13] if isinstance(row[13], list) else [],
    }


def build_summary(summary_rows: list[tuple[Any, ...]]) -> dict[str, Any]:
    """Aggregate priority summary rows into a summary dict."""
    summary: dict[str, Any] = {
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
    return summary
