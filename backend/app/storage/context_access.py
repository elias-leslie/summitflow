"""Context Access Log storage layer - Track memory entity expansions.

This module tracks when agents access (expand) memory entities like patterns,
observations, and diary entries. This data enables:
- Measuring which patterns are actually used
- Correlating pattern usage with task success/failure
- Calculating memory ROI (cost vs benefit)
"""

from __future__ import annotations

import logging
from typing import Any

from .connection import get_connection
from .memory_utils import normalize_timestamp

logger = logging.getLogger(__name__)


# Valid access sources
ACCESS_SOURCES = frozenset({"injection", "cli", "api"})

# Valid entity types
ENTITY_TYPES = frozenset({"pattern", "observation", "diary"})


def log_context_access(
    project_id: str,
    session_id: str,
    entity_type: str,
    entity_id: str,
    access_source: str = "api",
    task_id: str | None = None,
    task_outcome: str | None = None,
) -> dict[str, Any] | None:
    """Log a context access (entity expansion) event.

    Args:
        project_id: Project the access occurred in.
        session_id: Session that triggered the access.
        entity_type: Type of entity accessed ('pattern', 'observation', 'diary').
        entity_id: ID of the entity that was accessed.
        access_source: How the access happened ('injection', 'cli', 'api').
        task_id: Optional SummitFlow task being worked on.
        task_outcome: Optional task outcome (backfilled later).

    Returns:
        The created log entry, or None if logging failed.
    """
    # Validate access_source
    if access_source not in ACCESS_SOURCES:
        logger.warning(f"Invalid access_source: {access_source}, defaulting to 'api'")
        access_source = "api"

    # Validate entity_type
    if entity_type not in ENTITY_TYPES:
        logger.warning(f"Invalid entity_type: {entity_type}")
        # Still log it, but with the invalid type for debugging

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO context_access_log
                (project_id, session_id, entity_type, entity_id,
                 access_source, task_id, task_outcome)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id, project_id, session_id, entity_type, entity_id,
                      expanded_at, task_id, task_outcome, access_source, created_at
            """,
            (
                project_id,
                session_id,
                entity_type,
                entity_id,
                access_source,
                task_id,
                task_outcome,
            ),
        )
        row = cur.fetchone()
        conn.commit()

    if not row:
        return None

    return {
        "id": row[0],
        "project_id": row[1],
        "session_id": row[2],
        "entity_type": row[3],
        "entity_id": row[4],
        "expanded_at": normalize_timestamp(row[5]),
        "task_id": row[6],
        "task_outcome": row[7],
        "access_source": row[8],
        "created_at": normalize_timestamp(row[9]),
    }


def list_context_access(
    project_id: str,
    session_id: str | None = None,
    entity_type: str | None = None,
    access_source: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """List context access log entries with optional filters.

    Args:
        project_id: Project to query.
        session_id: Filter by session ID.
        entity_type: Filter by entity type.
        access_source: Filter by access source.
        limit: Maximum results.
        offset: Pagination offset.

    Returns:
        List of access log entries sorted by expanded_at descending.
    """
    conditions = ["project_id = %s"]
    params: list[Any] = [project_id]

    if session_id:
        conditions.append("session_id = %s")
        params.append(session_id)
    if entity_type:
        conditions.append("entity_type = %s")
        params.append(entity_type)
    if access_source:
        conditions.append("access_source = %s")
        params.append(access_source)

    params.extend([limit, offset])

    where_clause = " AND ".join(conditions)

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT id, project_id, session_id, entity_type, entity_id,
                   expanded_at, task_id, task_outcome, access_source, created_at
            FROM context_access_log
            WHERE {where_clause}
            ORDER BY expanded_at DESC
            LIMIT %s OFFSET %s
            """,
            params,
        )
        rows = cur.fetchall()

    return [
        {
            "id": row[0],
            "project_id": row[1],
            "session_id": row[2],
            "entity_type": row[3],
            "entity_id": row[4],
            "expanded_at": normalize_timestamp(row[5]),
            "task_id": row[6],
            "task_outcome": row[7],
            "access_source": row[8],
            "created_at": normalize_timestamp(row[9]),
        }
        for row in rows
    ]


def count_entity_access(
    project_id: str,
    entity_type: str | None = None,
    entity_id: str | None = None,
    access_source: str | None = None,
    hours: int | None = None,
) -> int:
    """Count access log entries matching filters.

    Args:
        project_id: Project to query.
        entity_type: Filter by entity type.
        entity_id: Filter by specific entity ID.
        access_source: Filter by access source.
        hours: Only count entries from last N hours.

    Returns:
        Count of matching entries.
    """
    conditions = ["project_id = %s"]
    params: list[Any] = [project_id]

    if entity_type:
        conditions.append("entity_type = %s")
        params.append(entity_type)
    if entity_id:
        conditions.append("entity_id = %s")
        params.append(entity_id)
    if access_source:
        conditions.append("access_source = %s")
        params.append(access_source)
    if hours:
        conditions.append("expanded_at >= NOW() - INTERVAL '%s hours'")
        params.append(hours)

    where_clause = " AND ".join(conditions)

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT COUNT(*) FROM context_access_log WHERE {where_clause}",
            params,
        )
        row = cur.fetchone()
        return row[0] if row else 0


def update_access_task_outcome(
    session_id: str,
    task_outcome: str,
) -> int:
    """Backfill task_outcome for all access log entries in a session.

    Called when a session ends to correlate pattern usage with success/failure.

    Args:
        session_id: Session to update.
        task_outcome: The outcome ('success', 'partial', 'failure').

    Returns:
        Number of entries updated.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE context_access_log
            SET task_outcome = %s
            WHERE session_id = %s
              AND task_outcome IS NULL
            """,
            (task_outcome, session_id),
        )
        updated: int = cur.rowcount or 0
        conn.commit()

    if updated > 0:
        logger.debug(f"Updated {updated} access log entries with outcome={task_outcome}")

    return updated


# =============================================================================
# Pattern Effectiveness Queries
# =============================================================================


def get_pattern_effectiveness(
    project_id: str,
    days: int = 30,
) -> list[dict[str, Any]]:
    """Calculate effectiveness metrics for each pattern.

    Returns success rate, usage count, and access distribution for patterns
    that have been accessed and have outcome data.

    Args:
        project_id: Project to analyze.
        days: Time window to analyze (default 30 days).

    Returns:
        List of pattern effectiveness data sorted by success rate descending.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                entity_id AS pattern_id,
                COUNT(*) AS total_access,
                COUNT(*) FILTER (WHERE task_outcome = 'success') AS success_count,
                COUNT(*) FILTER (WHERE task_outcome = 'partial') AS partial_count,
                COUNT(*) FILTER (WHERE task_outcome = 'failure') AS failure_count,
                COUNT(*) FILTER (WHERE access_source = 'injection') AS injection_count,
                COUNT(*) FILTER (WHERE access_source = 'api') AS api_count,
                COUNT(*) FILTER (WHERE access_source = 'cli') AS cli_count,
                COUNT(DISTINCT session_id) AS unique_sessions
            FROM context_access_log
            WHERE project_id = %s
              AND entity_type = 'pattern'
              AND expanded_at >= NOW() - INTERVAL '%s days'
            GROUP BY entity_id
            HAVING COUNT(*) FILTER (WHERE task_outcome IS NOT NULL) > 0
            ORDER BY
                COUNT(*) FILTER (WHERE task_outcome = 'success')::float /
                NULLIF(COUNT(*) FILTER (WHERE task_outcome IS NOT NULL), 0) DESC,
                COUNT(*) DESC
            """,
            (project_id, days),
        )
        rows = cur.fetchall()

    results = []
    for row in rows:
        total_with_outcome = row[2] + row[3] + row[4]  # success + partial + failure
        success_rate = row[2] / total_with_outcome if total_with_outcome > 0 else 0.0

        results.append(
            {
                "pattern_id": row[0],
                "total_access": row[1],
                "success_count": row[2],
                "partial_count": row[3],
                "failure_count": row[4],
                "success_rate": round(success_rate, 3),
                "injection_count": row[5],
                "api_count": row[6],
                "cli_count": row[7],
                "unique_sessions": row[8],
            }
        )

    return results


def get_pattern_sessions(
    project_id: str,
    pattern_id: str,
    outcome: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Get sessions where a pattern was accessed.

    Args:
        project_id: Project to query.
        pattern_id: Pattern ID to look up.
        outcome: Optional filter by outcome ('success', 'partial', 'failure').
        limit: Maximum sessions to return.

    Returns:
        List of session summaries with access details.
    """
    conditions = [
        "project_id = %s",
        "entity_type = 'pattern'",
        "entity_id = %s",
    ]
    params: list[Any] = [project_id, pattern_id]

    if outcome:
        conditions.append("task_outcome = %s")
        params.append(outcome)

    params.append(limit)
    where_clause = " AND ".join(conditions)

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT session_id, task_id, task_outcome, access_source, expanded_at
            FROM context_access_log
            WHERE {where_clause}
            ORDER BY expanded_at DESC
            LIMIT %s
            """,
            params,
        )
        rows = cur.fetchall()

    return [
        {
            "session_id": row[0],
            "task_id": row[1],
            "task_outcome": row[2],
            "access_source": row[3],
            "expanded_at": normalize_timestamp(row[4]),
        }
        for row in rows
    ]


def get_access_summary(
    project_id: str,
    days: int = 7,
) -> dict[str, Any]:
    """Get summary statistics for context access.

    Args:
        project_id: Project to analyze.
        days: Time window to analyze.

    Returns:
        Summary with counts by entity type, access source, and outcome.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE entity_type = 'pattern') AS patterns,
                COUNT(*) FILTER (WHERE entity_type = 'observation') AS observations,
                COUNT(*) FILTER (WHERE entity_type = 'diary') AS diary,
                COUNT(*) FILTER (WHERE access_source = 'injection') AS injection,
                COUNT(*) FILTER (WHERE access_source = 'api') AS api,
                COUNT(*) FILTER (WHERE access_source = 'cli') AS cli,
                COUNT(*) FILTER (WHERE task_outcome = 'success') AS success,
                COUNT(*) FILTER (WHERE task_outcome = 'partial') AS partial,
                COUNT(*) FILTER (WHERE task_outcome = 'failure') AS failure,
                COUNT(*) FILTER (WHERE task_outcome IS NULL) AS pending,
                COUNT(DISTINCT session_id) AS unique_sessions
            FROM context_access_log
            WHERE project_id = %s
              AND expanded_at >= NOW() - INTERVAL '%s days'
            """,
            (project_id, days),
        )
        row = cur.fetchone()

    if not row:
        return {"error": "No data found"}

    return {
        "project_id": project_id,
        "days": days,
        "total_access": row[0],
        "by_entity_type": {
            "pattern": row[1],
            "observation": row[2],
            "diary": row[3],
        },
        "by_access_source": {
            "injection": row[4],
            "api": row[5],
            "cli": row[6],
        },
        "by_outcome": {
            "success": row[7],
            "partial": row[8],
            "failure": row[9],
            "pending": row[10],
        },
        "unique_sessions": row[11],
    }
