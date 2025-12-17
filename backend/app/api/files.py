"""Files API - Centralized file scanning for all projects.

Scans project codebases directly using their root_path.

Endpoints:
- GET /api/projects/{project_id}/files - List files with filters
- GET /api/projects/{project_id}/files/summary - Get file statistics
- GET /api/projects/{project_id}/files/children - Get folder contents
- POST /api/projects/{project_id}/files/scan - Trigger file scan
"""

from typing import Any

from fastapi import APIRouter, HTTPException, Query, BackgroundTasks

from ..services import file_scanner
from ..storage.connection import get_connection

router = APIRouter()


def _get_project_root_path(project_id: str) -> str:
    """Get project root path from database."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT root_path FROM projects WHERE id = %s",
                (project_id,),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
            if not row[0]:
                raise HTTPException(
                    status_code=400,
                    detail=f"Project {project_id} has no root_path configured. Update the project with a root_path to enable file scanning.",
                )
            return row[0]


# =========================================================================
# Endpoints
# =========================================================================


@router.get("/{project_id}/files")
async def list_files(
    project_id: str,
    path: str | None = Query(None, description="Filter by path prefix"),
    extension: str | None = Query(None, description="Filter by extension (e.g., .py)"),
    bloat: str | None = Query(None, description="Filter by bloat level (warning, critical)"),
    stale: str | None = Query(None, description="Filter by stale status (fresh, stale, orphan)"),
    is_directory: bool | None = Query(None, description="Filter files or directories"),
    sort: str = Query("path", description="Sort by: path, lines_of_code, size_bytes, last_commit_days, reference_count"),
    dir: str = Query("asc", description="Sort direction: asc, desc"),
    limit: int = Query(100, ge=1, le=500, description="Results per page"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
) -> dict[str, Any]:
    """List files with filtering, sorting, and pagination."""
    # Verify project exists and has root_path
    _get_project_root_path(project_id)

    return file_scanner.list_files(
        project_id=project_id,
        path=path,
        extension=extension,
        bloat=bloat,
        stale=stale,
        is_directory=is_directory,
        sort=sort,
        direction=dir,
        limit=limit,
        offset=offset,
    )


@router.get("/{project_id}/files/summary")
async def get_summary(project_id: str) -> dict[str, Any]:
    """Get aggregate statistics from file audit."""
    # Verify project exists
    _get_project_root_path(project_id)

    return file_scanner.get_summary(project_id)


@router.get("/{project_id}/files/children")
async def get_children(
    project_id: str,
    path: str = Query("", description="Parent path (empty for root)"),
    sort: str = Query("name", description="Sort by: name, loc, size, files"),
    dir: str = Query("asc", description="Sort direction: asc, desc"),
    folders_first: bool = Query(True, description="Show folders before files"),
    include_files: bool = Query(True, description="Include files in response"),
) -> list[dict[str, Any]]:
    """Get immediate children (folders and files) for explorer view."""
    # Verify project exists
    _get_project_root_path(project_id)

    return file_scanner.get_children(
        project_id=project_id,
        path=path,
        sort=sort,
        direction=dir,
        folders_first=folders_first,
        include_files=include_files,
    )


@router.post("/{project_id}/files/scan")
async def trigger_scan(
    project_id: str,
    background_tasks: BackgroundTasks,
) -> dict[str, str]:
    """Trigger a file scan. Runs in background."""
    root_path = _get_project_root_path(project_id)

    def run_scan():
        scanner = file_scanner.FileScanner(project_id, root_path)
        scanner.scan()

    background_tasks.add_task(run_scan)

    return {
        "status": "scanning",
        "message": f"File scan started for {project_id}",
    }
