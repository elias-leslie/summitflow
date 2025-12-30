"""Memory health and lifecycle statistics storage functions.

Functions for checking memory system health and retrieving lifecycle metrics.
"""

from __future__ import annotations

from typing import Any

from .connection import get_connection

# Time thresholds for lifecycle checks
STUCK_QUEUE_THRESHOLD_HOURS = 1
STALE_PATTERN_THRESHOLD_DAYS = 30


def _fetch_count(cur: Any, query: str, params: list[Any]) -> int:
    """Execute SQL and return count from first row, or 0 if no result."""
    cur.execute(query, params)
    row = cur.fetchone()
    return row[0] if row else 0


def get_lifecycle_stats(project_id: str | None = None) -> dict[str, Any]:
    """Get lifecycle health statistics for the memory system.

    Args:
        project_id: Optional project filter. If None, returns global stats.

    Returns:
        Dict with lifecycle metrics:
        - failed_queue_count: Queue items in failed status
        - stuck_queue_count: Queue items stuck in processing > 1 hour
        - oldest_pending_age_minutes: Age of oldest pending queue item
        - unreflected_diary_count: Diary entries never reflected
        - stale_patterns_count: Applied patterns unused for 30+ days
        - pattern_status_breakdown: Count by status
    """
    project_filter = "AND project_id = %s" if project_id else ""
    params: list[Any] = [project_id] if project_id else []

    with get_connection() as conn, conn.cursor() as cur:
        # Failed queue count
        failed_queue_count = _fetch_count(
            cur,
            f"""
            SELECT COUNT(*)
            FROM observation_queue
            WHERE status = 'failed'
            {project_filter}
            """,
            params,
        )

        # Stuck queue count (processing for > 1 hour)
        stuck_params = [STUCK_QUEUE_THRESHOLD_HOURS, *params]
        stuck_queue_count = _fetch_count(
            cur,
            f"""
            SELECT COUNT(*)
            FROM observation_queue
            WHERE status = 'processing'
              AND created_at < NOW() - make_interval(hours := %s)
            {project_filter}
            """,
            stuck_params,
        )

        # Oldest pending age in minutes
        cur.execute(
            f"""
            SELECT EXTRACT(EPOCH FROM (NOW() - MIN(created_at))) / 60
            FROM observation_queue
            WHERE status = 'pending'
            {project_filter}
            """,
            params,
        )
        row = cur.fetchone()
        result = row[0] if row else None
        oldest_pending_age_minutes = int(result) if result else None

        # Unreflected diary count
        unreflected_diary_count = _fetch_count(
            cur,
            f"""
            SELECT COUNT(*)
            FROM session_diary
            WHERE reflected_at IS NULL
            {project_filter}
            """,
            params,
        )

        # Stale patterns count (applied but unused for 30+ days)
        stale_params = [STALE_PATTERN_THRESHOLD_DAYS, *params]
        stale_patterns_count = _fetch_count(
            cur,
            f"""
            SELECT COUNT(*)
            FROM learned_patterns
            WHERE status = 'applied'
              AND (last_used_at IS NULL OR last_used_at < NOW() - make_interval(days := %s))
            {project_filter}
            """,
            stale_params,
        )

        # Pattern status breakdown
        cur.execute(
            f"""
            SELECT status, COUNT(*)
            FROM learned_patterns
            WHERE 1=1
            {project_filter}
            GROUP BY status
            """,
            params,
        )
        pattern_status_breakdown = {row[0]: row[1] for row in cur.fetchall()}

    return {
        "failed_queue_count": failed_queue_count,
        "stuck_queue_count": stuck_queue_count,
        "oldest_pending_age_minutes": oldest_pending_age_minutes,
        "unreflected_diary_count": unreflected_diary_count,
        "stale_patterns_count": stale_patterns_count,
        "pattern_status_breakdown": pattern_status_breakdown,
    }
