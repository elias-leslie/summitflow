"""Explorer API - Unified codebase exploration endpoints.

Provides a consistent API for exploring:
- Files: Source code structure
- Database: Tables, columns, relationships
- Tasks: Celery tasks, schedules
- Endpoints: API routes, frontend pages

Endpoints:
- GET /api/projects/{id}/explorer - List entries with filters
- GET /api/projects/{id}/explorer/stats - Get summary statistics
- GET /api/projects/{id}/explorer/{type}/{path:path} - Get single entry
- POST /api/projects/{id}/explorer/scan - Trigger scan
- GET /api/projects/{id}/explorer/children - Get children for tree nav
"""

from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from ..services import explorer

router = APIRouter()


def _validate_entry_type(entry_type: str) -> None:
    """Validate entry type parameter."""
    valid_types = {"file", "table", "task", "endpoint"}
    if entry_type not in valid_types:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid entry type: {entry_type}. Must be one of: {', '.join(valid_types)}",
        )


def _validate_project_exists(project_id: str) -> None:
    """Validate project exists in database."""
    from ..storage.connection import get_connection

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM projects WHERE id = %s", (project_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail=f"Project {project_id} not found")


@router.get("/{project_id}/explorer")
async def list_entries(
    project_id: str,
    type: str | None = Query(None, description="Filter by entry type (file, table, task, endpoint)"),
    health: str | None = Query(None, description="Filter by health status (healthy, warning, error, unknown)"),
    path: str | None = Query(None, description="Filter by path prefix"),
    sort: str = Query("path", description="Sort field: path, name, health_status, last_scanned_at"),
    dir: str = Query("asc", description="Sort direction: asc, desc"),
    limit: int = Query(1000, ge=1, le=10000, description="Results per page"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
) -> dict[str, Any]:
    """List explorer entries with filtering, sorting, and pagination.

    Returns entries and statistics in a consistent format.
    """
    _validate_project_exists(project_id)

    if type:
        _validate_entry_type(type)

    # Build filters dict
    filters = {
        "type": type,
        "health": health,
        "path": path,
        "sort": sort,
        "dir": dir,
        "limit": limit,
        "offset": offset,
    }
    # Remove None values
    filters = {k: v for k, v in filters.items() if v is not None}

    entries = explorer.get_entries(project_id, filters)
    stats = explorer.get_stats(project_id)

    return {
        "entries": entries,
        "total": stats["total"],
        "stats": {
            "byHealth": stats["by_health"],
            "byType": stats["by_type"],
        },
    }


@router.get("/{project_id}/explorer/stats")
async def get_stats(project_id: str) -> dict[str, Any]:
    """Get aggregated statistics for explorer entries.

    Returns counts by type, by health status, total, and last scanned timestamp.
    """
    _validate_project_exists(project_id)

    stats = explorer.get_stats(project_id)

    return {
        "byType": stats["by_type"],
        "byHealth": stats["by_health"],
        "total": stats["total"],
        "lastScanned": stats["last_scanned"],
    }


@router.get("/{project_id}/explorer/children")
async def get_children(
    project_id: str,
    type: str = Query(..., description="Entry type (file, table, task, endpoint)"),
    path: str = Query("", description="Parent path (empty for root level)"),
) -> list[dict[str, Any]]:
    """Get direct children of a path for tree navigation.

    Returns immediate children only (not recursive).
    """
    _validate_project_exists(project_id)
    _validate_entry_type(type)

    return explorer.get_children(project_id, type, path)


@router.get("/{project_id}/explorer/{entry_type}/{path:path}")
async def get_entry(
    project_id: str,
    entry_type: str,
    path: str,
) -> dict[str, Any]:
    """Get a single explorer entry by type and path.

    Returns full entry details including metadata.
    """
    _validate_project_exists(project_id)
    _validate_entry_type(entry_type)

    entry = explorer.get_entry(project_id, entry_type, path)
    if not entry:
        raise HTTPException(
            status_code=404,
            detail=f"Entry not found: {entry_type}/{path}",
        )

    return entry


@router.post("/{project_id}/explorer/scan")
async def trigger_scan(
    project_id: str,
    background_tasks: BackgroundTasks,
    type: str | None = Query(None, description="Entry type to scan (file, table, task, endpoint). Scans all if not specified."),
) -> dict[str, Any]:
    """Trigger a scan for explorer entries.

    Runs in background. Returns immediately with scan status.
    """
    _validate_project_exists(project_id)

    if type:
        _validate_entry_type(type)

    # Define scan function
    def run_scan() -> None:
        if type:
            # Scan specific type
            result = explorer.scan(project_id, type)
            if not result.success:
                # Log error but don't raise - it's a background task
                from ..logging_config import get_logger
                logger = get_logger(__name__)
                logger.error(f"Scan failed for {type}: {result.error}")
        else:
            # Scan all registered types
            from ..services.explorer.types import list_registered_types
            for t in list_registered_types():
                explorer.scan(project_id, t)

    background_tasks.add_task(run_scan)

    return {
        "status": "scanning",
        "message": f"Scan started for {project_id}" + (f" (type: {type})" if type else " (all types)"),
        "type": type,
    }
