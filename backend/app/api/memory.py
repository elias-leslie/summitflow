"""Memory API - Memory system statistics, health, and global queries.

This module provides REST API endpoints for memory system monitoring:
- GET /api/memory/stats - System-wide memory statistics
- GET /api/observations - Global observations (all projects)
- GET /api/patterns - Global patterns (all projects)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Query
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


@router.get("/observations")
async def list_observations_global(
    project_id: str | None = Query(None, description="Filter by project"),
    agent_type: str | None = Query(None, description="Filter by agent type"),
    observation_type: str | None = Query(None, description="Filter by observation type"),
    session_id: str | None = Query(None, description="Filter by session ID"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> list[dict[str, Any]]:
    """List observations across all projects.

    Use project_id query param to filter to a specific project.
    Returns observations sorted by created_at descending (newest first).
    """
    return memory_storage.list_observations(
        project_id=project_id,
        agent_type=agent_type,
        observation_type=observation_type,
        session_id=session_id,
        limit=limit,
        offset=offset,
    )


@router.get("/patterns")
async def list_patterns_global(
    project_id: str | None = Query(None, description="Filter by project"),
    status: str | None = Query(None, description="Filter by status"),
    action: str | None = Query(None, description="Filter by action type"),
    pattern_type: str | None = Query(None, description="Filter by pattern type"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> list[dict[str, Any]]:
    """List patterns across all projects.

    Use project_id query param to filter to a specific project.
    Returns patterns sorted by created_at descending (newest first).
    """
    return memory_storage.list_patterns(
        project_id=project_id,
        status=status,
        action=action,
        pattern_type=pattern_type,
        limit=limit,
        offset=offset,
    )


class BulkPatternRequest(BaseModel):
    """Request body for bulk pattern operations."""

    pattern_ids: list[str]
    reason: str | None = None


class BulkPatternResponse(BaseModel):
    """Response for bulk pattern operations."""

    updated: int
    failed: int
    errors: list[str]


@router.post("/patterns/bulk-approve", response_model=BulkPatternResponse)
async def bulk_approve_patterns(
    request: BulkPatternRequest,
) -> BulkPatternResponse:
    """Bulk approve multiple patterns.

    Transitions patterns from 'pending' to 'approved'.
    """
    updated = 0
    failed = 0
    errors = []

    for pattern_id in request.pattern_ids:
        try:
            success = memory_storage.update_pattern_status(
                pattern_id=pattern_id,
                status="approved",
                reviewed_by=request.reason or "bulk-approve",
            )
            if success:
                updated += 1
            else:
                failed += 1
                errors.append(f"Pattern {pattern_id} not found")
        except Exception as e:
            failed += 1
            errors.append(f"Pattern {pattern_id}: {str(e)}")

    return BulkPatternResponse(updated=updated, failed=failed, errors=errors)


@router.post("/patterns/bulk-reject", response_model=BulkPatternResponse)
async def bulk_reject_patterns(
    request: BulkPatternRequest,
) -> BulkPatternResponse:
    """Bulk reject multiple patterns.

    Transitions patterns from 'pending' to 'rejected'.
    """
    updated = 0
    failed = 0
    errors = []

    for pattern_id in request.pattern_ids:
        try:
            success = memory_storage.update_pattern_status(
                pattern_id=pattern_id,
                status="rejected",
                reviewed_by=request.reason or "bulk-reject",
            )
            if success:
                updated += 1
            else:
                failed += 1
                errors.append(f"Pattern {pattern_id} not found")
        except Exception as e:
            failed += 1
            errors.append(f"Pattern {pattern_id}: {str(e)}")

    return BulkPatternResponse(updated=updated, failed=failed, errors=errors)


@router.get("/diary")
async def list_diary_global(
    project_id: str | None = Query(None, description="Filter by project"),
    outcome: str | None = Query(None, description="Filter by outcome"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> list[dict[str, Any]]:
    """List diary entries across all projects.

    Use project_id query param to filter to a specific project.
    Returns diary entries sorted by created_at descending (newest first).
    """
    return memory_storage.list_diary_entries(
        project_id=project_id,
        outcome=outcome,
        limit=limit,
        offset=offset,
    )
