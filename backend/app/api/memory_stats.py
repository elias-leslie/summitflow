"""Memory Stats API - System-wide memory statistics.

Endpoints:
- GET /memory/stats - System-wide memory statistics
- GET /memory/extraction - Global extraction settings
- PATCH /memory/extraction - Update global extraction settings
- GET /memory/index - Compact observation index for progressive disclosure
- GET /memory/observations - Batch fetch full observations by IDs
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Query
from psycopg import sql
from pydantic import BaseModel, Field

from ..api.hooks import get_filtering_metrics
from ..services.memory.fast_path import get_fast_path_metrics
from ..storage import memory as memory_storage
from ..storage.connection import get_connection
from ..utils.rate_limiter import (
    get_extraction_metrics,
    get_global_extraction_settings,
    set_global_extraction_settings,
)
from .memory_models import FastPathMetrics, FilteringMetrics, LifecycleStats, MemoryStats

router = APIRouter()


# --- Global Extraction Settings ---


class ExtractionSettingsResponse(BaseModel):
    """Global extraction settings response."""

    enabled: bool = Field(description="Whether AI extraction is enabled globally")
    rpm_limit: int = Field(description="Requests per minute limit (60=unlimited)")
    current_rpm: int = Field(description="Current requests in the last minute")
    requests_today: int = Field(description="Total requests today")


class ExtractionSettingsUpdate(BaseModel):
    """Update global extraction settings."""

    enabled: bool | None = Field(None, description="Enable/disable extraction globally")
    rpm_limit: int | None = Field(None, ge=0, le=60, description="RPM limit (0=off, 5/10/15/30/60)")


@router.get("/memory/extraction", response_model=ExtractionSettingsResponse)
async def get_extraction_settings() -> ExtractionSettingsResponse:
    """Get global AI extraction settings."""
    settings = get_global_extraction_settings()
    metrics = get_extraction_metrics()

    return ExtractionSettingsResponse(
        enabled=settings["enabled"],
        rpm_limit=settings["rpm_limit"],
        current_rpm=metrics["current_minute_count"],
        requests_today=metrics["requests_today"],
    )


@router.patch("/memory/extraction", response_model=ExtractionSettingsResponse)
async def update_extraction_settings(
    update: ExtractionSettingsUpdate,
) -> ExtractionSettingsResponse:
    """Update global AI extraction settings."""
    settings = set_global_extraction_settings(
        enabled=update.enabled,
        rpm_limit=update.rpm_limit,
    )
    metrics = get_extraction_metrics()

    return ExtractionSettingsResponse(
        enabled=settings["enabled"],
        rpm_limit=settings["rpm_limit"],
        current_rpm=metrics["current_minute_count"],
        requests_today=metrics["requests_today"],
    )


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

        # Get last access time from context_access_log
        access_params: list[str] = []
        if project_id:
            access_params.append(project_id)
        cur.execute(
            sql.SQL("""
            SELECT MAX(expanded_at)
            FROM context_access_log
            WHERE 1=1
            {project_filter}
            """).format(project_filter=project_filter),
            tuple(access_params),
        )
        access_row = cur.fetchone()
        last_access_time = access_row[0].isoformat() if access_row and access_row[0] else None

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

    # Get fast-path extraction metrics
    fp_metrics = get_fast_path_metrics()
    fast_path = FastPathMetrics(
        hits=int(fp_metrics["fast_path_hits"]),
        misses=int(fp_metrics["fast_path_misses"]),
        total=int(fp_metrics["fast_path_total"]),
        hit_rate=float(fp_metrics["fast_path_hit_rate"]),
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
        fast_path=fast_path,
        last_access_time=last_access_time,
    )


# --- Progressive Disclosure: Observation Index ---


class ObservationIndexItem(BaseModel):
    """Compact observation summary for index view."""

    id: str = Field(description="Observation UUID")
    title: str = Field(description="Observation title")
    observation_type: str = Field(description="Type: error, operational, pattern, etc.")
    tokens_to_read: int = Field(description="Estimated tokens to read full observation")
    created_at: datetime = Field(description="When observation was created")


class ObservationIndexResponse(BaseModel):
    """Compact observation index for progressive disclosure."""

    items: list[ObservationIndexItem] = Field(description="Observation summaries")
    total: int = Field(description="Total observations matching filter")
    index_tokens: int = Field(description="Tokens consumed by this index")
    full_tokens: int = Field(description="Tokens if full observations were included")


def _estimate_tokens(text: str | None) -> int:
    """Estimate token count from text (rough: ~4 chars per token)."""
    if not text:
        return 0
    return len(text) // 4


@router.get("/memory/index", response_model=ObservationIndexResponse)
async def get_observation_index(
    project_id: str = Query(..., description="Project ID to filter observations"),
    limit: int = Query(50, ge=1, le=200, description="Max observations to return"),
) -> ObservationIndexResponse:
    """Get compact observation index for progressive disclosure.

    Returns minimal info (id, title, type, token cost) so agent can decide
    which observations to fetch in full. Much cheaper than injecting full content.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, title, observation_type, narrative, subtitle,
                   CASE
                       WHEN jsonb_typeof(facts) = 'array' THEN jsonb_array_length(facts)
                       WHEN jsonb_typeof(facts) = 'object' THEN (
                           SELECT COUNT(*) FROM jsonb_object_keys(facts)
                       )::int
                       ELSE 0
                   END as facts_count,
                   created_at
            FROM observations
            WHERE project_id = %s
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (project_id, limit),
        )
        rows = cur.fetchall()

    items: list[ObservationIndexItem] = []
    total_full_tokens = 0

    for row in rows:
        obs_id, title, obs_type, narrative, subtitle, facts_count, created_at = row

        # Estimate tokens for full observation
        full_tokens = (
            _estimate_tokens(title)
            + _estimate_tokens(subtitle)
            + _estimate_tokens(narrative)
            + (facts_count * 20)  # ~20 tokens per fact
        )
        total_full_tokens += full_tokens

        items.append(
            ObservationIndexItem(
                id=str(obs_id),
                title=title or "(untitled)",
                observation_type=obs_type or "unknown",
                tokens_to_read=full_tokens,
                created_at=created_at,
            )
        )

    # Estimate index tokens (id + title + type + ~10 overhead per item)
    index_tokens = sum(
        len(item.id) // 4 + len(item.title) // 4 + len(item.observation_type) // 4 + 10
        for item in items
    )

    return ObservationIndexResponse(
        items=items,
        total=len(items),
        index_tokens=index_tokens,
        full_tokens=total_full_tokens,
    )
