"""Pipeline metrics API endpoint."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..services.health_cache import HealthCache
from ..storage.connection import get_connection
from .pipeline_models import PipelineStatsResponse
from .pipeline_stats import compute_pipeline_stats

router = APIRouter()

# Cache pipeline stats for 30 seconds
_pipeline_stats_cache: HealthCache[PipelineStatsResponse] | None = None


def _get_pipeline_stats_cache() -> HealthCache[PipelineStatsResponse]:
    """Get the singleton pipeline stats cache instance."""
    global _pipeline_stats_cache
    if _pipeline_stats_cache is None:
        _pipeline_stats_cache = HealthCache[PipelineStatsResponse]()
    return _pipeline_stats_cache


def _verify_project_exists(project_id: str) -> None:
    """Verify that a project exists, raising 404 if not."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM projects WHERE id = %s", (project_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail=f"Project {project_id} not found")


async def _fetch_pipeline_stats(project_id: str) -> PipelineStatsResponse:
    """
    Internal function to fetch fresh pipeline statistics.

    This function is separated to enable caching. It computes all metrics
    from the tasks table and autonomous settings.
    """
    import asyncio

    # Run database queries in thread pool
    return await asyncio.to_thread(compute_pipeline_stats, project_id)


@router.get("/pipeline/stats", response_model=PipelineStatsResponse)
async def get_pipeline_stats(project_id: str) -> PipelineStatsResponse:
    """
    Get pipeline health statistics for a project.

    Returns task distribution, throughput metrics, self-healing statistics,
    verification data, partial merge rates, and autonomous execution state.

    Uses caching with 30-second TTL for performance.

    Args:
        project_id: Project ID to get stats for

    Returns:
        Pipeline statistics including all metrics defined in PipelineStatsResponse
    """
    _verify_project_exists(project_id)

    # Use cache with 30-second TTL (similar to health endpoint pattern)
    cache = _get_pipeline_stats_cache()

    # Create a project-specific fetch function
    async def fetch_fn() -> PipelineStatsResponse:
        return await _fetch_pipeline_stats(project_id)

    result = await cache.get_or_refresh(fetch_fn)
    if result is None:
        raise HTTPException(status_code=503, detail="Pipeline stats unavailable")

    return result
