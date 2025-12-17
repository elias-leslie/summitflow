"""Sitemap API - Dynamic endpoint discovery and health monitoring.

Endpoints:
- GET /api/projects/{project_id}/sitemap/entries - List all entries with filters
- GET /api/projects/{project_id}/sitemap/entries/{id} - Get single entry detail
- POST /api/projects/{project_id}/sitemap/discover - Trigger discovery scan
- POST /api/projects/{project_id}/sitemap/check/{id} - Check single entry health
- POST /api/projects/{project_id}/sitemap/check-all - Check all entries health
- GET /api/projects/{project_id}/sitemap/health-summary - Aggregate health stats
- POST /api/projects/{project_id}/sitemap/register - Manually register entry
- DELETE /api/projects/{project_id}/sitemap/entries/{id} - Remove entry
- GET /api/projects/{project_id}/sitemap/history-stats - Get history stats
- POST /api/projects/{project_id}/sitemap/cleanup-history - Cleanup old history
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..services.sitemap_service import SitemapService

router = APIRouter()


# =========================================================================
# Request/Response Models
# =========================================================================


class SitemapEntry(BaseModel):
    """Sitemap entry response model."""

    id: int
    port: int
    path: str
    method: str
    entry_type: str
    source: str | None
    title: str | None
    parent_path: str | None
    health_status: str
    console_errors: int
    console_warnings: int
    http_status: int | None
    response_time_ms: int | None
    last_error_message: str | None
    last_checked_at: str | None
    discovered_at: str | None


class SitemapListResponse(BaseModel):
    """Response for listing sitemap entries."""

    total: int
    entries: list[SitemapEntry]


class HealthSummaryResponse(BaseModel):
    """Response for health summary."""

    total: int
    healthy: int
    warning: int
    error: int
    unknown: int
    by_port: dict[str, dict[str, int]]


class RegisterRequest(BaseModel):
    """Request to manually register an entry."""

    port: int = Field(..., description="Port number (3000, 8000, etc.)")
    path: str = Field(..., description="URL path")
    method: str = Field("GET", description="HTTP method")
    entry_type: str = Field("manual", description="Entry type")
    title: str | None = None


class DiscoveryResponse(BaseModel):
    """Response from discovery scan."""

    backend_discovered: int
    frontend_discovered: int
    total_saved: int


class HealthCheckResponse(BaseModel):
    """Response from health check."""

    success: bool
    entry_id: int | None = None
    health_status: str | None = None
    http_status: int | None = None
    response_time_ms: int | None = None
    error: str | None = None


class CheckAllResponse(BaseModel):
    """Response from check all health."""

    checked: int
    healthy: int
    warning: int
    error: int


class HistoryStatsResponse(BaseModel):
    """Response for history statistics."""

    total_rows: int
    oldest_entry: str | None


class CleanupResponse(BaseModel):
    """Response from cleanup operation."""

    deleted: int
    retention_days: int


# =========================================================================
# Endpoints
# =========================================================================


@router.get("/{project_id}/sitemap/entries", response_model=SitemapListResponse)
def list_entries(
    project_id: str,
    port: int | None = Query(None, description="Filter by port"),
    health_status: str | None = Query(None, description="Filter by health status"),
    entry_type: str | None = Query(None, description="Filter by entry type"),
    limit: int = Query(100, ge=1, le=500, description="Max results"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
) -> SitemapListResponse:
    """List sitemap entries with optional filters."""
    try:
        service = SitemapService(project_id)
        entries, total = service.get_entries(
            port=port,
            health_status=health_status,
            entry_type=entry_type,
            limit=limit,
            offset=offset,
        )
        return SitemapListResponse(total=total, entries=entries)  # type: ignore
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/{project_id}/sitemap/entries/{entry_id}", response_model=SitemapEntry)
def get_entry(project_id: str, entry_id: int) -> SitemapEntry:
    """Get a single sitemap entry by ID."""
    try:
        service = SitemapService(project_id)
        entry = service.get_entry(entry_id)
        if not entry:
            raise HTTPException(status_code=404, detail="Entry not found")
        return SitemapEntry(**entry)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/{project_id}/sitemap/discover", response_model=DiscoveryResponse)
async def trigger_discovery(project_id: str) -> DiscoveryResponse:
    """Trigger discovery scan for new endpoints."""
    try:
        service = SitemapService(project_id)
        result = await service.run_discovery()
        return DiscoveryResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/{project_id}/sitemap/check/{entry_id}", response_model=HealthCheckResponse)
async def check_entry_health(project_id: str, entry_id: int) -> HealthCheckResponse:
    """Check health of a single sitemap entry."""
    try:
        service = SitemapService(project_id)
        result = await service.check_entry_health(entry_id)
        return HealthCheckResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/{project_id}/sitemap/check-all", response_model=CheckAllResponse)
async def check_all_health(project_id: str) -> CheckAllResponse:
    """Check health of all sitemap entries."""
    try:
        service = SitemapService(project_id)
        result = await service.check_all_health()
        return CheckAllResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/{project_id}/sitemap/health-summary", response_model=HealthSummaryResponse)
def get_health_summary(project_id: str) -> HealthSummaryResponse:
    """Get aggregate health statistics."""
    try:
        service = SitemapService(project_id)
        summary = service.get_health_summary()
        return HealthSummaryResponse(**summary)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/{project_id}/sitemap/register", response_model=SitemapEntry)
def register_entry(project_id: str, request: RegisterRequest) -> SitemapEntry:
    """Manually register a new sitemap entry."""
    try:
        service = SitemapService(project_id)
        entry = service.register_entry(
            port=request.port,
            path=request.path,
            method=request.method,
            entry_type=request.entry_type,
            title=request.title,
        )
        return SitemapEntry(**entry)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.delete("/{project_id}/sitemap/entries/{entry_id}")
def delete_entry(project_id: str, entry_id: int) -> dict:
    """Delete a sitemap entry."""
    try:
        service = SitemapService(project_id)
        deleted = service.delete_entry(entry_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Entry not found")
        return {"success": True, "deleted_id": entry_id}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


# =========================================================================
# Maintenance Endpoints
# =========================================================================


@router.get("/{project_id}/sitemap/history-stats", response_model=HistoryStatsResponse)
def get_history_stats(project_id: str) -> HistoryStatsResponse:
    """Get health history statistics."""
    try:
        service = SitemapService(project_id)
        stats = service.get_history_stats()
        return HistoryStatsResponse(**stats)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/{project_id}/sitemap/cleanup-history", response_model=CleanupResponse)
def cleanup_history(
    project_id: str,
    days: int = Query(7, ge=1, le=30, description="Days to retain"),
) -> CleanupResponse:
    """Cleanup old health history."""
    try:
        service = SitemapService(project_id)
        deleted = service.cleanup_old_history(days=days)
        return CleanupResponse(deleted=deleted, retention_days=days)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
