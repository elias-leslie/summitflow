"""Memory API - Memory system statistics and health.

This module provides REST API endpoints for memory system monitoring:
- GET /api/memory/stats - System-wide memory statistics
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from ..storage import memory as memory_storage
from ..storage.connection import get_connection

router = APIRouter()


class MemoryStats(BaseModel):
    """Memory system statistics."""

    queue_depth: int
    queue_pending: int
    observations_today: int
    observation_success_rate: float
    token_spend_24h: int
    health: str  # 'healthy', 'degraded', 'unhealthy'
    health_details: dict[str, Any] | None = None


@router.get("/memory/stats", response_model=MemoryStats)
async def get_memory_stats() -> MemoryStats:
    """Get memory system statistics.

    Returns queue depth, observation counts, success rates, and health status.
    """
    now = datetime.now(UTC)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday = now - timedelta(days=1)

    with get_connection() as conn, conn.cursor() as cur:
        # Queue statistics
        cur.execute(
            """
            SELECT
                COUNT(*) FILTER (WHERE status = 'pending') as pending,
                COUNT(*) FILTER (WHERE status = 'processing') as processing,
                COUNT(*) FILTER (WHERE status = 'processed'
                    AND processed_at >= %s) as processed_24h,
                COUNT(*) FILTER (WHERE status = 'failed'
                    AND processed_at >= %s) as failed_24h
            FROM observation_queue
            WHERE created_at >= %s
            """,
            (yesterday, yesterday, yesterday),
        )
        queue_row = cur.fetchone()
        pending = queue_row[0] or 0
        processing = queue_row[1] or 0
        processed_24h = queue_row[2] or 0
        failed_24h = queue_row[3] or 0

        queue_depth = pending + processing

        # Calculate success rate
        total_completed = processed_24h + failed_24h
        success_rate = (
            (processed_24h / total_completed * 100) if total_completed > 0 else 100.0
        )

        # Observations today
        cur.execute(
            """
            SELECT COUNT(*)
            FROM observations
            WHERE created_at >= %s
            """,
            (today_start,),
        )
        observations_today = cur.fetchone()[0] or 0

        # Token spend (discovery_tokens from observations in last 24h)
        cur.execute(
            """
            SELECT COALESCE(SUM(discovery_tokens), 0)
            FROM observations
            WHERE created_at >= %s
            """,
            (yesterday,),
        )
        token_spend_24h = cur.fetchone()[0] or 0

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

    return MemoryStats(
        queue_depth=queue_depth,
        queue_pending=pending,
        observations_today=observations_today,
        observation_success_rate=round(success_rate, 1),
        token_spend_24h=token_spend_24h,
        health=health,
        health_details=health_details if health_details else None,
    )
