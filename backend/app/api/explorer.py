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
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from ..services import explorer
from ..storage import explorer as explorer_storage
from ..storage import scan_history
from . import explorer_helpers as helpers
from .dependencies import validate_project_exists

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
    validate_project_exists(project_id)

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
    validate_project_exists(project_id)
    stats = explorer.get_stats(project_id)
    return helpers.format_stats_response(stats)


@router.get("/{project_id}/explorer/children")
async def get_children(
    project_id: str,
    type: str = Query(..., description="Entry type (file, table, task, endpoint)"),
    path: str = Query("", description="Parent path (empty for root level)"),
) -> list[dict[str, Any]]:
    """Get direct children of a path for tree navigation."""
    validate_project_exists(project_id)
    helpers.validate_entry_type(type)
    return explorer.get_children(project_id, type, path)


@router.get("/{project_id}/explorer/symbols/search")
async def search_symbols(
    project_id: str,
    q: str = Query(..., min_length=1, description="Search query"),
    language: str | None = Query(None, description="Optional language filter"),
    kind: str | None = Query(None, description="Optional kind filter"),
    limit: int = Query(20, ge=1, le=100, description="Maximum results"),
) -> dict[str, Any]:
    """Search project symbols by name, signature, or summary."""
    validate_project_exists(project_id)
    rows = explorer_storage.search_symbols(
        project_id,
        q,
        language=language,
        kind=kind,
        limit=limit,
    )
    return {
        "query": q,
        "count": len(rows),
        "items": rows,
    }


@router.get("/{project_id}/explorer/symbols/detail")
async def get_symbol_detail(
    project_id: str,
    symbol_id: str = Query(..., min_length=1, description="Stable symbol id"),
    context_lines: int = Query(0, ge=0, le=20, description="Extra lines before/after symbol"),
) -> dict[str, Any]:
    """Get symbol metadata plus source and linked file entry."""
    validate_project_exists(project_id)
    symbol = explorer_storage.get_symbol(project_id, symbol_id)
    if not symbol:
        raise HTTPException(status_code=404, detail="Symbol not found")

    source = _read_symbol_source(project_id, symbol, context_lines)
    file_entry = explorer_storage.get_entry(project_id, "file", symbol["file_path"])
    return {
        "symbol": symbol,
        "source": source,
        "file_entry": file_entry,
    }


@router.post("/{project_id}/explorer/scan")
async def trigger_scan(
    project_id: str,
    background_tasks: BackgroundTasks,
    type: str | None = Query(None, description="Entry type to scan. Scans all if not specified."),
    triggered_by: str = Query("manual", description="Source that initiated the scan"),
    triggered_by_session: str | None = Query(None, description="Claude session ID if applicable"),
    trigger_context_json: str | None = Query(
        None, description="JSON-encoded additional context", alias="trigger_context"
    ),
) -> dict[str, Any]:
    """Trigger a scan for explorer entries. Runs in background."""
    validate_project_exists(project_id)

    if type:
        helpers.validate_entry_type(type)

    trigger_context = helpers.parse_trigger_context(trigger_context_json)

    # Initialize scan state tracking
    explorer.start_scan(project_id, type)

    # Record scan in history
    scan_type = type or "full"
    scan_id = scan_history.record_scan_start(
        project_id=project_id,
        scan_type=scan_type,
        triggered_by=triggered_by,
        triggered_by_session=triggered_by_session,
        trigger_context=trigger_context,
    )

    # Run scan with progress tracking in background (pass scan_id for completion recording)
    background_tasks.add_task(
        helpers.run_scan_and_record,
        project_id,
        type,
        scan_id,
    )

    return {
        "status": "scanning",
        "message": f"Scan started for {project_id}"
        + (f" (type: {type})" if type else " (all types)"),
        "type": type,
        "scan_id": scan_id,
    }


@router.get("/{project_id}/explorer/scan-history")
async def get_scan_history(
    project_id: str,
    days: int = Query(30, ge=1, le=365, description="Number of days to look back"),
    scan_type: str | None = Query(None, description="Filter by scan type"),
) -> dict[str, Any]:
    """Get scan history with sparkline data and summary."""
    validate_project_exists(project_id)
    return {
        "scans": scan_history.get_scan_history(project_id, days=days, scan_type=scan_type),
        "sparkline_data": scan_history.get_sparkline_data(project_id, days=days),
        "summary": scan_history.get_summary(project_id, days=days),
    }


@router.get("/{project_id}/explorer/scan-comparison")
async def get_scan_comparison(
    project_id: str,
    before: int = Query(..., description="Scan ID for 'before' snapshot"),
    after: int = Query(..., description="Scan ID for 'after' snapshot"),
) -> dict[str, Any]:
    """Compare two scans with metrics delta."""
    validate_project_exists(project_id)
    comparison = scan_history.get_scan_comparison(before, after)
    if not comparison:
        raise HTTPException(status_code=404, detail="One or both scans not found")
    return comparison


@router.get("/{project_id}/explorer/entry/{entry_id}")
async def get_entry_by_id(project_id: str, entry_id: int) -> dict[str, Any]:
    """Get a single explorer entry by ID."""
    validate_project_exists(project_id)
    entry = explorer_storage.get_entry_by_id(entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail=f"Entry {entry_id} not found")
    if entry.get("project_id") != project_id:
        raise HTTPException(status_code=404, detail=f"Entry {entry_id} not found in project")
    return entry


def _read_symbol_source(symbol_project_id: str, symbol: dict[str, Any], context_lines: int) -> str:
    """Read symbol source from disk using stored offsets, with optional surrounding lines."""
    root_path = explorer.get_project_root(symbol_project_id)
    if not root_path:
        raise HTTPException(status_code=400, detail="Project has no root_path configured")

    file_path = Path(root_path) / symbol["file_path"]
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Symbol source file not found")

    if context_lines == 0:
        with file_path.open("rb") as handle:
            handle.seek(int(symbol["byte_offset"]))
            source_bytes = handle.read(int(symbol["byte_length"]))
        return source_bytes.decode("utf-8", errors="replace")

    lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
    start = max(0, int(symbol["start_line"]) - 1 - context_lines)
    end = min(len(lines), int(symbol["end_line"]) + context_lines)
    return "\n".join(lines[start:end])


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
    validate_project_exists(project_id)

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
    validate_project_exists(project_id)
    return explorer_storage.get_coverage_gaps(project_id)


@router.get("/{project_id}/explorer/{entry_type}/{path:path}")
async def get_entry(project_id: str, entry_type: str, path: str) -> dict[str, Any]:
    """Get a single explorer entry by type and path."""
    validate_project_exists(project_id)
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
    validate_project_exists(project_id)
    return await helpers.dispatch_hatchet_workflow(
        "summitflow.run_page_health_checks",
        project_id,
        "Health check started. Results will update page entries.",
    )


@router.post("/{project_id}/explorer/regenerate-index")
async def regenerate_index(project_id: str) -> dict[str, Any]:
    """Regenerate .index.yaml file for a project."""
    validate_project_exists(project_id)
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
    validate_project_exists(project_id)
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
