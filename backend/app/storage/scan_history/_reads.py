"""Scan history read operations - queries and aggregations."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from ..connection import get_connection
from ._helpers import (
    build_triggers_breakdown,
    classify_complexity_trend,
    compute_comparison_delta,
    row_to_scan,
)

_SCAN_SELECT = """
    SELECT id, project_id, scan_type, triggered_by, triggered_by_session,
           triggered_by_user, trigger_context, started_at, completed_at,
           duration_ms, status, error_message, metrics, entries_found,
           entries_saved, previous_scan_id, metrics_delta, created_at
    FROM scan_history
"""


def get_scan_history(
    project_id: str,
    days: int = 30,
    scan_type: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Get scan history for a project."""
    days = min(days, 365)
    cutoff = datetime.now(UTC) - timedelta(days=days)

    with get_connection() as conn, conn.cursor() as cur:
        query = _SCAN_SELECT + " WHERE project_id = %s AND started_at >= %s"
        params: list[Any] = [project_id, cutoff]

        if scan_type:
            query += " AND scan_type = %s"
            params.append(scan_type)

        query += " ORDER BY started_at DESC LIMIT %s"
        params.append(limit)

        cur.execute(query, params)
        return [row_to_scan(row) for row in cur.fetchall()]


def get_latest_scan(
    project_id: str,
    *,
    statuses: list[str] | None = None,
) -> dict[str, Any] | None:
    """Return the most recent scan for a project, optionally filtered by status."""
    with get_connection() as conn, conn.cursor() as cur:
        query = _SCAN_SELECT + " WHERE project_id = %s"
        params: list[Any] = [project_id]

        if statuses:
            query += " AND status = ANY(%s)"
            params.append(statuses)

        query += " ORDER BY started_at DESC LIMIT 1"
        cur.execute(query, params)
        row = cur.fetchone()

    return row_to_scan(row) if row else None


def get_scan_comparison(
    scan_id_before: int,
    scan_id_after: int,
) -> dict[str, Any] | None:
    """Get comparison between two scans."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            _SCAN_SELECT + " WHERE id IN (%s, %s)",
            (scan_id_before, scan_id_after),
        )
        rows = cur.fetchall()
        if len(rows) != 2:
            return None

        scans = {row[0]: row_to_scan(row) for row in rows}
        before = scans.get(scan_id_before)
        after = scans.get(scan_id_after)

        if not before or not after:
            return None

        delta, delta_pct = compute_comparison_delta(before, after)
        return {
            "before_scan": before,
            "after_scan": after,
            "before_metrics": before.get("metrics", {}),
            "after_metrics": after.get("metrics", {}),
            "delta": delta,
            "delta_pct": delta_pct,
        }


def get_sparkline_data(project_id: str, days: int = 30) -> dict[str, Any]:
    """Get aggregated data for sparkline visualization."""
    days = min(days, 365)
    cutoff = datetime.now(UTC) - timedelta(days=days)

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT DATE(started_at) as scan_date,
                   COUNT(*) as scan_count,
                   AVG((metrics->>'complexity')::float) as avg_complexity,
                   SUM(CASE WHEN (metrics->>'high_priority_count')::int > 0 THEN 1 ELSE 0 END)
            FROM scan_history
            WHERE project_id = %s AND started_at >= %s AND status = 'completed'
            GROUP BY DATE(started_at)
            ORDER BY scan_date
            """,
            (project_id, cutoff),
        )
        rows = cur.fetchall()

        dates: list[str] = []
        complexity: list[float | None] = []
        targets: list[int] = []
        high_priority: list[int] = []

        for row in rows:
            dates.append(row[0].strftime("%Y-%m-%d") if row[0] else "")
            complexity.append(float(row[2]) if row[2] else None)
            targets.append(int(row[1]) if row[1] else 0)
            high_priority.append(int(row[3]) if row[3] else 0)

        return {"dates": dates, "complexity": complexity, "targets": targets, "high_priority": high_priority}


def _fetch_complexity_trend(cur: Any, project_id: str) -> str:
    """Query weekly complexity data and classify trend."""
    cur.execute(
        """
        WITH weekly AS (
            SELECT
                CASE WHEN started_at >= NOW() - INTERVAL '7 days' THEN 'recent'
                     WHEN started_at >= NOW() - INTERVAL '14 days' THEN 'previous'
                END as period,
                AVG((metrics->>'complexity')::float) as avg_complexity
            FROM scan_history
            WHERE project_id = %s AND started_at >= NOW() - INTERVAL '14 days'
                  AND status = 'completed' AND metrics->>'complexity' IS NOT NULL
            GROUP BY period
        )
        SELECT period, avg_complexity FROM weekly WHERE period IS NOT NULL
        """,
        (project_id,),
    )
    weekly_data = {row[0]: row[1] for row in cur.fetchall()}
    return classify_complexity_trend(weekly_data)


def get_summary(project_id: str, days: int = 30) -> dict[str, Any]:
    """Get summary statistics for scan history."""
    days = min(days, 365)
    cutoff = datetime.now(UTC) - timedelta(days=days)

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) as total_scans, AVG(duration_ms) as avg_duration
            FROM scan_history
            WHERE project_id = %s AND started_at >= %s AND status = 'completed'
            """,
            (project_id, cutoff),
        )
        stats_row = cur.fetchone()
        total_scans = stats_row[0] if stats_row else 0
        avg_duration_ms = float(stats_row[1]) if stats_row and stats_row[1] else None

        cur.execute(
            """
            SELECT triggered_by, COUNT(*) as count
            FROM scan_history
            WHERE project_id = %s AND started_at >= %s
            GROUP BY triggered_by ORDER BY count DESC
            """,
            (project_id, cutoff),
        )
        triggers_breakdown, most_active_trigger = build_triggers_breakdown(
            cur.fetchall(), total_scans
        )
        complexity_trend = _fetch_complexity_trend(cur, project_id)

    return {
        "total_scans": total_scans,
        "avg_duration_ms": avg_duration_ms,
        "complexity_trend": complexity_trend,
        "most_active_trigger": most_active_trigger,
        "triggers_breakdown": triggers_breakdown,
    }
