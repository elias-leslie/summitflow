"""Explorer API - Unified codebase exploration endpoints.

Provides a consistent API for exploring:
- Files: Source code structure
- Database: Tables, columns, relationships
- Tasks: Background tasks, schedules
- Endpoints: API routes
- Pages: Frontend pages (Next.js)

Endpoints:
- GET /api/projects/{id}/explorer - List entries with filters
- GET /api/projects/{id}/explorer/stats - Get summary statistics
- GET /api/projects/{id}/explorer/{type}/{path:path} - Get single entry
- POST /api/projects/{id}/explorer/scan - Trigger scan
- GET /api/projects/{id}/explorer/children - Get children for tree nav
"""

import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from ..services import explorer
from ..storage import explorer as explorer_storage
from . import explorer_helpers as helpers

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/{project_id}/explorer")
async def list_entries(
    project_id: str,
    type: str | None = Query(
        None, description="Filter by entry type (file, table, task, endpoint)"
    ),
    health: str | None = Query(
        None, description="Filter by health status (healthy, warning, error, unknown)"
    ),
    path: str | None = Query(None, description="Filter by path prefix"),
    association: str | None = Query(
        None, description="Filter by association status (orphan, is_component)"
    ),
    sort: str = Query("path", description="Sort field: path, name, health_status, last_scanned_at"),
    dir: str = Query("asc", description="Sort direction: asc, desc"),
    limit: int = Query(1000, ge=1, le=10000, description="Results per page"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
) -> dict[str, Any]:
    """List explorer entries with filtering, sorting, and pagination."""
    helpers.validate_project_exists(project_id)

    if type:
        helpers.validate_entry_type(type)

    if association:
        helpers.validate_association(association)

    filters = helpers.build_filters(type, health, path, association, sort, dir, limit, offset)
    entries = explorer.get_entries(project_id, filters)

    # For page entries, include sub_elements if any exist
    helpers.enrich_page_entries_with_sub_elements(entries, type)

    # Get stats filtered by type if type filter is applied
    stats = explorer.get_stats(project_id, entry_type=type)

    return helpers.format_list_entries_response(entries, stats)


@router.get("/{project_id}/explorer/stats")
async def get_stats(project_id: str) -> dict[str, Any]:
    """Get aggregated statistics for explorer entries."""
    helpers.validate_project_exists(project_id)
    stats = explorer.get_stats(project_id)
    return helpers.format_stats_response(stats)


@router.get("/{project_id}/explorer/children")
async def get_children(
    project_id: str,
    type: str = Query(..., description="Entry type (file, table, task, endpoint)"),
    path: str = Query("", description="Parent path (empty for root level)"),
) -> list[dict[str, Any]]:
    """Get direct children of a path for tree navigation."""
    helpers.validate_project_exists(project_id)
    helpers.validate_entry_type(type)
    return explorer.get_children(project_id, type, path)


@router.get("/{project_id}/explorer/scan/status")
async def get_scan_status(project_id: str) -> dict[str, Any]:
    """Get current scan status for polling."""
    helpers.validate_project_exists(project_id)
    return explorer.get_scan_status(project_id)


@router.post("/{project_id}/explorer/scan")
async def trigger_scan(
    project_id: str,
    background_tasks: BackgroundTasks,
    type: str | None = Query(None, description="Entry type to scan. Scans all if not specified."),
) -> dict[str, Any]:
    """Trigger a scan for explorer entries. Runs in background."""
    helpers.validate_project_exists(project_id)

    if type:
        helpers.validate_entry_type(type)

    # Run scan in background
    background_tasks.add_task(
        explorer.run_scan_with_tracking,
        project_id,
        type,
    )

    return {
        "status": "scanning",
        "message": f"Scan started for {project_id}"
        + (f" (type: {type})" if type else " (all types)"),
        "type": type,
    }


@router.get("/{project_id}/explorer/entry/{entry_id}")
async def get_entry_by_id(project_id: str, entry_id: int) -> dict[str, Any]:
    """Get a single explorer entry by ID."""
    helpers.validate_project_exists(project_id)
    entry = explorer_storage.get_entry_by_id(entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail=f"Entry {entry_id} not found")
    if entry.get("project_id") != project_id:
        raise HTTPException(status_code=404, detail=f"Entry {entry_id} not found in project")
    return entry


@router.get("/{project_id}/explorer/refactor-targets")
async def get_refactor_targets(
    project_id: str,
    priority: str | None = Query(None, description="Filter by priority: high, medium"),
    min_complexity: float | None = Query(None, description="Minimum complexity score"),
    min_lines: int | None = Query(None, description="Minimum lines of code"),
    limit: int = Query(50, ge=1, le=200, description="Max results"),
    code_only: bool = Query(True, description="Filter to code files only"),
    extensions: str | None = Query(None, description="Comma-separated extensions (.py,.ts)"),
) -> dict[str, Any]:
    """Get files that are candidates for refactoring."""
    helpers.validate_project_exists(project_id)

    if priority:
        helpers.validate_priority(priority)

    ext_list = extensions.split(",") if extensions else None

    result = explorer_storage.get_refactor_targets(
        project_id,
        priority=priority,
        min_complexity=min_complexity,
        min_lines=min_lines,
        limit=limit,
        code_only=code_only,
        extensions=ext_list,
    )

    helpers.add_stale_metadata_warning(result, project_id)
    return result


@router.get("/{project_id}/analysis/coverage-gaps")
async def get_coverage_gaps(project_id: str) -> dict[str, Any]:
    """Get endpoints, pages, and tables without capability links."""
    helpers.validate_project_exists(project_id)
    return explorer_storage.get_coverage_gaps(project_id)


@router.get("/{project_id}/explorer/{entry_type}/{path:path}")
async def get_entry(project_id: str, entry_type: str, path: str) -> dict[str, Any]:
    """Get a single explorer entry by type and path."""
    helpers.validate_project_exists(project_id)
    helpers.validate_entry_type(entry_type)
    entry = explorer.get_entry(project_id, entry_type, path)
    if not entry:
        raise HTTPException(
            status_code=404,
            detail=f"Entry not found: {entry_type}/{path}",
        )
    return entry


@router.post("/{project_id}/explorer/health-check")
async def trigger_health_check(
    project_id: str, background_tasks: BackgroundTasks
) -> dict[str, Any]:
    """Trigger health checks for all page entries."""
    helpers.validate_project_exists(project_id)
    return await helpers.dispatch_hatchet_workflow(
        "summitflow.run_page_health_checks",
        project_id,
        "Health check started. Results will update page entries.",
    )


@router.post("/{project_id}/explorer/regenerate-index")
async def regenerate_index(project_id: str) -> dict[str, Any]:
    """Regenerate .index.yaml file for a project."""
    helpers.validate_project_exists(project_id)
    from ..services.explorer import write_index_file

    return helpers.format_index_regeneration_response(project_id, write_index_file(project_id))


@router.post("/explorer/regenerate-all-indexes")
async def regenerate_all_indexes() -> dict[str, Any]:
    """Regenerate .index.yaml files for all projects."""
    from ..services.explorer import write_all_index_files

    return helpers.format_all_indexes_response(write_all_index_files())


@router.post("/{project_id}/explorer/regenerate-refactor-tasks")
async def regenerate_refactor_tasks(
    project_id: str,
    background_tasks: BackgroundTasks,
    sync: bool = Query(False, description="Run synchronously instead of via background workflow"),
) -> dict[str, Any]:
    """Delete existing refactor tasks and regenerate from current scan."""
    helpers.validate_project_exists(project_id)
    if sync:
        from ..tasks.autonomous.task_generation import regenerate_refactor_tasks_sync

        try:
            result = regenerate_refactor_tasks_sync(project_id)
        except Exception as e:
            logger.exception("Sync regeneration failed for %s", project_id)
            result = {"error": str(e), "deleted_count": 0, "created_count": 0, "scanned_count": 0}
        status = "completed" if "error" not in result else "error"
        return {"status": status, "project_id": project_id, **result}
    return await helpers.dispatch_hatchet_workflow(
        "summitflow.regenerate_refactor_tasks",
        project_id,
        "Refactor task regeneration started. Existing tasks will be deleted and new ones created.",
    )
