"""Memory Stats API - System-wide memory statistics.

Endpoints:
- GET /memory/stats - System-wide memory statistics
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Query
from psycopg import sql

from ..api.hooks import get_filtering_metrics
from ..storage import memory as memory_storage
from ..storage.connection import get_connection
from .memory_models import FilteringMetrics, LifecycleStats, MemoryStats

router = APIRouter()


@router.get("/memory/stats", response_model=MemoryStats)
async def get_memory_stats(
    project_id: str | None = Query(None, description="Filter by project"),
) -> MemoryStats:
    """Get memory system statistics.

    Returns queue depth, observation counts, success rates, and health status.
    Optionally filter by project_id.
    """
    now = datetime.now(UTC)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday = now - timedelta(days=1)

    # Build project filter using sql.SQL for safe composition
    project_filter = sql.SQL("AND project_id = %s") if project_id else sql.SQL("")

    with get_connection() as conn, conn.cursor() as cur:
        # Queue statistics
        queue_params: list[datetime | str] = [yesterday, yesterday, yesterday]
        if project_id:
            queue_params.append(project_id)
        cur.execute(
            sql.SQL("""
            SELECT
                COUNT(*) FILTER (WHERE status = 'pending') as pending,
                COUNT(*) FILTER (WHERE status = 'processing') as processing,
                COUNT(*) FILTER (WHERE status = 'processed'
                    AND processed_at >= %s) as processed_24h,
                COUNT(*) FILTER (WHERE status = 'failed'
                    AND processed_at >= %s) as failed_24h
            FROM observation_queue
            WHERE created_at >= %s
            {project_filter}
            """).format(project_filter=project_filter),
            tuple(queue_params),
        )
        queue_row = cur.fetchone()
        pending = queue_row[0] if queue_row else 0
        processing = queue_row[1] if queue_row else 0
        processed_24h = queue_row[2] if queue_row else 0
        failed_24h = queue_row[3] if queue_row else 0

        queue_depth = pending + processing

        # Calculate success rate
        total_completed = processed_24h + failed_24h
        success_rate = (processed_24h / total_completed * 100) if total_completed > 0 else 100.0

        # Observations today
        obs_params: list[datetime | str] = [today_start]
        if project_id:
            obs_params.append(project_id)
        cur.execute(
            sql.SQL("""
            SELECT COUNT(*)
            FROM observations
            WHERE created_at >= %s
            {project_filter}
            """).format(project_filter=project_filter),
            tuple(obs_params),
        )
        obs_row = cur.fetchone()
        observations_today = obs_row[0] if obs_row else 0

        # Token spend (discovery_tokens from observations in last 24h)
        token_params: list[datetime | str] = [yesterday]
        if project_id:
            token_params.append(project_id)
        cur.execute(
            sql.SQL("""
            SELECT COALESCE(SUM(discovery_tokens), 0)
            FROM observations
            WHERE created_at >= %s
            {project_filter}
            """).format(project_filter=project_filter),
            tuple(token_params),
        )
        token_row = cur.fetchone()
        token_spend_24h = token_row[0] if token_row else 0

    # Determine health status
    health = "healthy"
    health_details = {}

    if queue_depth > 100:
        health = "degraded"
        health_details["queue_depth"] = f"High queue depth: {queue_depth}"
    if queue_depth > 500:
        health = "unhealthy"
        health_details["queue_depth"] = f"Critical queue depth: {queue_depth}"

    if success_rate < 90:
        if health == "healthy":
            health = "degraded"
        health_details["success_rate"] = f"Low success rate: {success_rate:.1f}%"
    if success_rate < 70:
        health = "unhealthy"
        health_details["success_rate"] = f"Critical success rate: {success_rate:.1f}%"

    # Get filtering metrics from Redis
    filter_metrics = get_filtering_metrics()

    # Get lifecycle stats
    lifecycle_data = memory_storage.get_lifecycle_stats(project_id)
    lifecycle = LifecycleStats(
        failed_queue_count=lifecycle_data["failed_queue_count"],
        stuck_queue_count=lifecycle_data["stuck_queue_count"],
        oldest_pending_age_minutes=lifecycle_data["oldest_pending_age_minutes"],
        unreflected_diary_count=lifecycle_data["unreflected_diary_count"],
        stale_patterns_count=lifecycle_data["stale_patterns_count"],
        pattern_status_breakdown=lifecycle_data["pattern_status_breakdown"],
    )

    return MemoryStats(
        queue_depth=queue_depth,
        queue_pending=pending,
        observations_today=observations_today,
        observation_success_rate=round(success_rate, 1),
        token_spend_24h=token_spend_24h,
        health=health,
        health_details=health_details if health_details else None,
        filtering=FilteringMetrics(**filter_metrics),
        lifecycle=lifecycle,
    )
