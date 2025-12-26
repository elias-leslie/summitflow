"""Memory patterns storage - Learned patterns management.

This module handles the learned_patterns table operations.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from psycopg import sql
from psycopg.rows import TupleRow

from .agent_configs import is_memory_feature_enabled
from .connection import get_connection
from .memory_utils import (
    build_where_clause as _build_where_clause,
)
from .memory_utils import (
    json_or_default as _json_or_default,
)

logger = logging.getLogger(__name__)

# Column list for DRY queries
PATTERN_COLUMNS = """
    id, project_id, pattern_type, title, content, rationale,
    source_diary_ids, source_observation_ids, action, target_pattern_id,
    status, confidence, usage_count, last_used_at, superseded_by,
    applied_to_rules_at, created_at, reviewed_at, reviewed_by, reflected_by
""".strip()


# =============================================================================
# Learned Patterns Storage
# =============================================================================


def create_pattern(
    project_id: str,
    pattern_type: str,
    title: str,
    content: str,
    action: str = "add",
    rationale: str | None = None,
    source_diary_ids: list[str] | None = None,
    source_observation_ids: list[str] | None = None,
    target_pattern_id: str | None = None,
    confidence: float | None = None,
    reflected_by: str | None = None,
    skip_memory_check: bool = False,
) -> dict[str, Any] | None:
    """Create a learned pattern.

    Args:
        skip_memory_check: If True, bypass the memory enabled check.

    Returns:
        The created pattern, or None if memory is disabled.
    """
    if not skip_memory_check and not is_memory_feature_enabled(project_id, "patterns"):
        logger.debug(f"Memory patterns disabled for {project_id}, skipping pattern")
        return None

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO learned_patterns
                (project_id, pattern_type, title, content, action, rationale,
                 source_diary_ids, source_observation_ids, target_pattern_id, confidence,
                 reflected_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, project_id, pattern_type, title, content, rationale,
                      source_diary_ids, source_observation_ids, action, target_pattern_id,
                      status, confidence, usage_count, last_used_at, superseded_by,
                      applied_to_rules_at, created_at, reviewed_at, reviewed_by, reflected_by
            """,
            (
                project_id,
                pattern_type,
                title,
                content,
                action,
                rationale,
                _json_or_default(source_diary_ids, "[]"),
                _json_or_default(source_observation_ids, "[]"),
                target_pattern_id,
                confidence,
                reflected_by,
            ),
        )
        row = cur.fetchone()
        conn.commit()

    return _pattern_row_to_dict(row)


def get_pattern(pattern_id: str) -> dict[str, Any] | None:
    """Get a pattern by ID."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT {PATTERN_COLUMNS} FROM learned_patterns WHERE id = %s",
            (pattern_id,),
        )
        row = cur.fetchone()

    if not row:
        return None
    return _pattern_row_to_dict(row)


def list_patterns(
    project_id: str | None = None,
    status: str | None = None,
    action: str | None = None,
    pattern_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """List patterns with optional filters.

    Args:
        project_id: Filter by project (None = all projects)
        status: Filter by status
        action: Filter by action type
        pattern_type: Filter by pattern type
        limit: Maximum results
        offset: Pagination offset

    Returns:
        List of patterns sorted by created_at descending.
    """
    where_clause, params = _build_where_clause(
        {
            "project_id": project_id,
            "status": status,
            "action": action,
            "pattern_type": pattern_type,
        }
    )
    params.extend([limit, offset])

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            sql.SQL(f"""
            SELECT {PATTERN_COLUMNS}
            FROM learned_patterns
            WHERE {{where_clause}}
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
            """).format(where_clause=where_clause),
            params,
        )
        rows = cur.fetchall()

    return [_pattern_row_to_dict(row) for row in rows]


def count_patterns(
    project_id: str | None = None,
    status: str | None = None,
    action: str | None = None,
    pattern_type: str | None = None,
) -> int:
    """Count patterns with optional filters.

    Args:
        project_id: Filter by project (None = all projects)
        status: Filter by status
        action: Filter by action type
        pattern_type: Filter by pattern type

    Returns:
        Total count of matching patterns.
    """
    where_clause, params = _build_where_clause(
        {
            "project_id": project_id,
            "status": status,
            "action": action,
            "pattern_type": pattern_type,
        }
    )

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            sql.SQL("SELECT COUNT(*) FROM learned_patterns WHERE {where_clause}").format(
                where_clause=where_clause
            ),
            params,
        )
        row = cur.fetchone()
        return row[0] if row else 0


def get_stale_patterns(project_id: str, days: int = 30) -> list[dict[str, Any]]:
    """Get patterns that are applied but unused for N days."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {PATTERN_COLUMNS}
            FROM learned_patterns
            WHERE project_id = %s
              AND status = 'applied'
              AND (last_used_at IS NULL OR last_used_at < NOW() - INTERVAL '%s days')
            ORDER BY last_used_at ASC NULLS FIRST
            """,
            (project_id, days),
        )
        rows = cur.fetchall()

    return [_pattern_row_to_dict(row) for row in rows]


def update_pattern_status(
    pattern_id: str,
    status: str,
    reviewed_by: str | None = None,
) -> bool:
    """Update pattern status.

    Returns:
        True if updated, False if not found.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE learned_patterns
            SET status = %s, reviewed_at = NOW(), reviewed_by = %s
            WHERE id = %s
            """,
            (status, reviewed_by, pattern_id),
        )
        updated = cur.rowcount > 0
        conn.commit()

    return updated


def mark_pattern_applied(pattern_id: str) -> bool:
    """Mark pattern as applied to rules.

    Returns:
        True if updated, False if not found.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE learned_patterns
            SET status = 'applied', applied_to_rules_at = NOW()
            WHERE id = %s
            """,
            (pattern_id,),
        )
        updated = cur.rowcount > 0
        conn.commit()

    return updated


def increment_pattern_usage(pattern_id: str) -> bool:
    """Increment pattern usage count.

    Returns:
        True if updated, False if not found.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE learned_patterns
            SET usage_count = usage_count + 1, last_used_at = NOW()
            WHERE id = %s
            """,
            (pattern_id,),
        )
        updated = cur.rowcount > 0
        conn.commit()

    return updated


def _pattern_row_to_dict(row: TupleRow | tuple[Any, ...] | None) -> dict[str, Any]:
    """Convert pattern row to dict.

    Handles both old 19-column rows and new 20-column rows with reflected_by.
    """
    if row is None:
        raise ValueError("Row cannot be None")
    confidence = row[11]
    if isinstance(confidence, Decimal):
        confidence = float(confidence)

    result = {
        "id": str(row[0]),
        "project_id": row[1],
        "pattern_type": row[2],
        "title": row[3],
        "content": row[4],
        "rationale": row[5],
        "source_diary_ids": row[6],
        "source_observation_ids": row[7],
        "action": row[8],
        "target_pattern_id": str(row[9]) if row[9] else None,
        "status": row[10],
        "confidence": confidence,
        "usage_count": row[12],
        "last_used_at": row[13].isoformat() if row[13] else None,
        "superseded_by": str(row[14]) if row[14] else None,
        "applied_to_rules_at": row[15].isoformat() if row[15] else None,
        "created_at": row[16].isoformat() if row[16] else None,
        "reviewed_at": row[17].isoformat() if row[17] else None,
        "reviewed_by": row[18],
    }
    # Handle both old (19 cols) and new (20 cols with reflected_by) row formats
    if len(row) >= 20:
        result["reflected_by"] = row[19]
    else:
        result["reflected_by"] = None
    return result
