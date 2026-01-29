"""Helper functions for the Explorer API.

Contains validation, response formatting, and background task helpers
to keep the main router file focused on endpoint definitions.
"""

import json
from typing import Any

from fastapi import HTTPException

from ..services import explorer
from ..storage import explorer as explorer_storage
from ..storage import scan_history
from ..storage.connection import get_connection


def validate_entry_type(entry_type: str) -> None:
    """Validate entry type parameter."""
    valid_types = {"file", "table", "task", "endpoint", "page", "dependency"}
    if entry_type not in valid_types:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid entry type: {entry_type}. Must be one of: {', '.join(sorted(valid_types))}",
        )


def validate_project_exists(project_id: str) -> None:
    """Validate project exists in database."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM projects WHERE id = %s", (project_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail=f"Project {project_id} not found")


def validate_association(association: str) -> None:
    """Validate association filter parameter."""
    if association not in {"orphan", "linked", "is_component"}:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid association: {association}. Must be: orphan, linked, is_component",
        )


def validate_priority(priority: str) -> None:
    """Validate priority filter parameter."""
    if priority not in {"high", "medium"}:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid priority: {priority}. Must be: high, medium",
        )


def build_filters(
    type: str | None,
    health: str | None,
    path: str | None,
    association: str | None,
    sort: str,
    dir: str,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    """Build filters dictionary for explorer queries."""
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
    return {k: v for k, v in filters.items() if v is not None}


def parse_trigger_context(trigger_context_json: str | None) -> dict[str, Any] | None:
    """Parse trigger context JSON safely."""
    if not trigger_context_json:
        return None
    try:
        result: dict[str, Any] = json.loads(trigger_context_json)
        return result
    except json.JSONDecodeError:
        return None


def enrich_page_entries_with_sub_elements(
    entries: list[dict[str, Any]], type_filter: str | None
) -> None:
    """Add sub_elements to page entries in-place.

    Args:
        entries: List of explorer entries to potentially enrich
        type_filter: Type filter from the query (if any)
    """
    if type_filter == "page" or not type_filter:
        from ..storage import explorer_sub_elements

        for entry in entries:
            if entry.get("entry_type") == "page":
                sub_els = explorer_sub_elements.get_elements_for_entry(entry["id"])
                entry["sub_elements"] = [
                    {
                        "id": el["id"],
                        "selector": el["selector"],
                        "element_type": el["element_type"],
                        "label": el.get("label"),
                        "last_captured_at": el.get("last_captured_at"),
                        "capture_count": el.get("capture_count", 0),
                    }
                    for el in sub_els
                ]


def format_list_entries_response(
    entries: list[dict[str, Any]],
    stats: dict[str, Any],
) -> dict[str, Any]:
    """Format the response for list_entries endpoint."""
    return {
        "entries": entries,
        "total": stats["total"],
        "stats": {
            "byHealth": stats["by_health"],
            "byType": stats["by_type"],
            "lastScanned": stats["last_scanned"],
        },
    }


def format_stats_response(stats: dict[str, Any]) -> dict[str, Any]:
    """Format the response for get_stats endpoint."""
    return {
        "byType": stats["by_type"],
        "byHealth": stats["by_health"],
        "total": stats["total"],
        "lastScanned": stats["last_scanned"],
    }


def get_total_complexity(project_id: str) -> float:
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


async def run_scan_and_record(
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
        total_complexity = get_total_complexity(project_id)

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


def add_stale_metadata_warning(result: dict[str, Any], project_id: str) -> None:
    """Add stale metadata warning to result if applicable (in-place)."""
    stale_count = explorer_storage.count_stale_metadata_entries(project_id)
    if stale_count > 0:
        result["warning"] = {
            "message": f"{stale_count} files have outdated metadata. Run a fresh scan.",
            "stale_count": stale_count,
        }


def dispatch_celery_task(task_name: str, project_id: str, message: str) -> dict[str, Any]:
    """Dispatch a Celery task and return standardized response."""
    from celery import current_app

    result = current_app.send_task(task_name, args=[project_id])

    return {
        "status": "started",
        "project_id": project_id,
        "task_id": result.id,
        "message": message,
    }


def format_index_regeneration_response(project_id: str, result: str | None) -> dict[str, Any]:
    """Format the response for index regeneration endpoint."""
    return {
        "status": "success" if result else "failed",
        "project_id": project_id,
        "path": result,
        **({"error": "Could not write index file (check project root_path)"} if not result else {}),
    }


def format_all_indexes_response(results: dict[str, Any]) -> dict[str, Any]:
    """Format the response for regenerate all indexes endpoint."""
    success = [k for k, v in results.items() if v is not None]
    failed = [k for k, v in results.items() if v is None]

    return {
        "status": "completed",
        "success_count": len(success),
        "failed_count": len(failed),
        "success": success,
        "failed": failed,
    }
