"""Explorer API - Unified codebase exploration endpoints.

Provides a consistent API for exploring:
- Files: Source code structure
- Database: Tables, columns, relationships
- Tasks: Celery tasks, schedules
- Endpoints: API routes
- Pages: Frontend pages (Next.js)

Endpoints:
- GET /api/projects/{id}/explorer - List entries with filters
- GET /api/projects/{id}/explorer/stats - Get summary statistics
- GET /api/projects/{id}/explorer/{type}/{path:path} - Get single entry
- POST /api/projects/{id}/explorer/scan - Trigger scan
- GET /api/projects/{id}/explorer/children - Get children for tree nav
"""

import json
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from ..services import explorer
from ..storage import explorer as explorer_storage
from ..storage import scan_history
from ..storage.connection import get_connection

router = APIRouter()


def _validate_entry_type(entry_type: str) -> None:
    """Validate entry type parameter."""
    valid_types = {"file", "table", "task", "endpoint", "page"}
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
    type: str | None = Query(
        None, description="Filter by entry type (file, table, task, endpoint)"
    ),
    health: str | None = Query(
        None, description="Filter by health status (healthy, warning, error, unknown)"
    ),
    path: str | None = Query(None, description="Filter by path prefix"),
    association: str | None = Query(
        None,
        description="Filter by association status (orphan, linked, is_component)",
    ),
    sort: str = Query("path", description="Sort field: path, name, health_status, last_scanned_at"),
    dir: str = Query("asc", description="Sort direction: asc, desc"),
    limit: int = Query(1000, ge=1, le=10000, description="Results per page"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
) -> dict[str, Any]:
    """List explorer entries with filtering, sorting, and pagination.

    Returns entries with association_status field and statistics.
    """
    _validate_project_exists(project_id)

    if type:
        _validate_entry_type(type)

    if association and association not in {"orphan", "linked", "is_component"}:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid association: {association}. Must be: orphan, linked, is_component",
        )

    # Build filters dict
    filters = {
        "type": type,
        "health": health,
        "path": path,
        "association": association,
        "sort": sort,
        "dir": dir,
        "limit": limit,
        "offset": offset,
    }
    # Remove None values
    filters = {k: v for k, v in filters.items() if v is not None}

    entries = explorer.get_entries(project_id, filters)
    # Get stats filtered by type if type filter is applied
    stats = explorer.get_stats(project_id, entry_type=type)

    return {
        "entries": entries,
        "total": stats["total"],
        "stats": {
            "byHealth": stats["by_health"],
            "byType": stats["by_type"],
            "lastScanned": stats["last_scanned"],
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


@router.get("/{project_id}/explorer/scan/status")
async def get_scan_status(project_id: str) -> dict[str, Any]:
    """Get current scan status for polling.

    Returns status, progress, and timing information.
    Poll this endpoint to track scan completion.
    """
    _validate_project_exists(project_id)

    return explorer.get_scan_status(project_id)


@router.post("/{project_id}/explorer/scan")
async def trigger_scan(
    project_id: str,
    background_tasks: BackgroundTasks,
    type: str | None = Query(
        None,
        description="Entry type to scan (file, table, task, endpoint). Scans all if not specified.",
    ),
    triggered_by: str = Query(
        "manual",
        description="Source that initiated the scan (manual, refactor_it, daily_qa_scan, audit_it)",
    ),
    triggered_by_session: str | None = Query(
        None,
        description="Claude session ID if applicable",
    ),
    trigger_context_json: str | None = Query(
        None,
        description="JSON-encoded additional context about the trigger (phase, goal, etc.)",
        alias="trigger_context",
    ),
) -> dict[str, Any]:
    """Trigger a scan for explorer entries.

    Runs in background. Returns immediately with scan status and scan_id.
    Poll GET /scan/status for completion.
    """
    _validate_project_exists(project_id)

    if type:
        _validate_entry_type(type)

    # Parse trigger context if provided
    trigger_context: dict[str, Any] | None = None
    if trigger_context_json:
        try:
            trigger_context = json.loads(trigger_context_json)
        except json.JSONDecodeError:
            trigger_context = None

    # Record scan in history
    scan_type = type or "full"
    scan_id = scan_history.record_scan_start(
        project_id=project_id,
        scan_type=scan_type,
        triggered_by=triggered_by,
        triggered_by_session=triggered_by_session,
        trigger_context=trigger_context,
    )

    # Initialize scan state tracking
    explorer.start_scan(project_id, type)

    # Run scan with progress tracking in background (pass scan_id for completion recording)
    background_tasks.add_task(
        _run_scan_and_record,
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


def _get_total_complexity(project_id: str) -> float:
    """Calculate total complexity score from file entries.

    Called after scan completion to snapshot the current complexity state.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
                SELECT COALESCE(SUM((metadata->>'complexity_score')::float), 0)
                FROM explorer_entries
                WHERE project_id = %s
                  AND entry_type = 'file'
                  AND metadata->>'complexity_score' IS NOT NULL
                """,
            (project_id,),
        )
        row = cur.fetchone()
        return round(row[0], 2) if row and row[0] else 0.0


async def _run_scan_and_record(
    project_id: str,
    entry_type: str | None,
    scan_id: int,
) -> None:
    """Run scan and record completion in scan_history."""
    try:
        # Run the actual scan with tracking
        explorer.run_scan_with_tracking(project_id, entry_type)

        # Get scan results from scan_states
        scan_status = explorer.get_scan_status(project_id)
        results = scan_status.get("results", [])

        # Calculate totals
        entries_found = sum(r.get("entries_found", 0) for r in results)
        entries_saved = sum(r.get("entries_saved", 0) for r in results)

        # Calculate total complexity from file entries (snapshot at scan time)
        total_complexity = _get_total_complexity(project_id)

        # Build metrics from results
        metrics = {
            "types_scanned": len(results),
            "by_type": {r["entry_type"]: r for r in results},
            "complexity": total_complexity,  # Snapshot for sparkline trend
        }

        scan_history.record_scan_complete(
            scan_id=scan_id,
            status="completed" if scan_status.get("status") == "completed" else "failed",
            error_message=scan_status.get("error"),
            metrics=metrics,
            entries_found=entries_found,
            entries_saved=entries_saved,
        )
    except Exception as e:
        scan_history.record_scan_complete(
            scan_id=scan_id,
            status="failed",
            error_message=str(e),
        )


@router.get("/{project_id}/explorer/scan-history")
async def get_scan_history(
    project_id: str,
    days: int = Query(30, ge=1, le=365, description="Number of days to look back"),
    scan_type: str | None = Query(None, description="Filter by scan type"),
) -> dict[str, Any]:
    """Get scan history with sparkline data and summary.

    Returns list of scans, aggregated chart data, and summary statistics.
    Cached for 60 seconds.
    """
    _validate_project_exists(project_id)

    scans = scan_history.get_scan_history(project_id, days=days, scan_type=scan_type)
    sparkline = scan_history.get_sparkline_data(project_id, days=days)
    summary = scan_history.get_summary(project_id, days=days)

    return {
        "scans": scans,
        "sparkline_data": sparkline,
        "summary": summary,
    }


@router.get("/{project_id}/explorer/scan-comparison")
async def get_scan_comparison(
    project_id: str,
    before: int = Query(..., description="Scan ID for 'before' snapshot"),
    after: int = Query(..., description="Scan ID for 'after' snapshot"),
) -> dict[str, Any]:
    """Compare two scans with metrics delta.

    Returns both scans with computed differences.
    """
    _validate_project_exists(project_id)

    comparison = scan_history.get_scan_comparison(before, after)
    if not comparison:
        raise HTTPException(status_code=404, detail="One or both scans not found")

    return comparison


@router.get("/{project_id}/explorer/entry/{entry_id}/capabilities")
async def get_entry_capabilities(
    project_id: str,
    entry_id: int,
) -> list[dict[str, Any]]:
    """Get all capabilities linked to an explorer entry.

    Returns list of capabilities with link info.
    """
    _validate_project_exists(project_id)

    caps = explorer_storage.get_entry_capabilities(entry_id)
    return caps


@router.get("/{project_id}/explorer/refactor-targets")
async def get_refactor_targets(
    project_id: str,
    priority: str | None = Query(None, description="Filter by priority: high, medium"),
    min_complexity: float | None = Query(None, description="Minimum complexity score"),
    min_lines: int | None = Query(None, description="Minimum lines of code"),
    limit: int = Query(50, ge=1, le=200, description="Max results"),
    code_only: bool = Query(True, description="Filter to code files only (.py, .ts, etc)"),
    extensions: str | None = Query(None, description="Comma-separated extensions (.py,.ts)"),
) -> dict[str, Any]:
    """Get files that are candidates for refactoring.

    Returns files with high complexity or line count, sorted by priority.
    By default, only returns code files (Python, TypeScript, JavaScript).
    """
    _validate_project_exists(project_id)

    if priority and priority not in {"high", "medium"}:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid priority: {priority}. Must be: high, medium",
        )

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

    # Add stale metadata warning if applicable
    stale_count = explorer_storage.count_stale_metadata_entries(project_id)
    if stale_count > 0:
        result["warning"] = {
            "message": f"{stale_count} files have outdated metadata. Run a fresh scan.",
            "stale_count": stale_count,
        }

    return result


@router.get("/{project_id}/analysis/coverage-gaps")
async def get_coverage_gaps(project_id: str) -> dict[str, Any]:
    """Get endpoints, pages, and tables without capability links.

    Returns entities that are not covered by any capability,
    indicating potential gaps in TDD coverage.
    """
    _validate_project_exists(project_id)

    return explorer_storage.get_coverage_gaps(project_id)


@router.get("/{project_id}/analysis/multi-capability-files")
async def get_multi_capability_files(
    project_id: str,
    min_capabilities: int = Query(3, ge=2, le=20, description="Minimum capabilities per file"),
    limit: int = Query(50, ge=1, le=200, description="Max results"),
) -> dict[str, Any]:
    """Get files linked to multiple capabilities (potential god files).

    Returns files that implement or are involved in many capabilities,
    which may indicate overly complex modules that should be split.
    """
    _validate_project_exists(project_id)

    return explorer_storage.get_multi_capability_files(
        project_id,
        min_capabilities=min_capabilities,
        limit=limit,
    )


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
